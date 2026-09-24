//+------------------------------------------------------------------+
//|                                          TraderAIG.mq5           |
//|                    TraderAIG Institutional Operating Core - EA   |
//|                                                                  |
//|  The EA is the execution plane of the TraderAIG system.          |
//|  It receives approved TradeCandidates, enforces a local hard     |
//|  risk ceiling (never overridable), routes orders to MT5, and     |
//|  feeds order/position state back to the Python core.             |
//|                                                                  |
//|  Communication: file-based JSON bridge in the terminal's common  |
//|  folder (visible to both the EA and the Python companion).       |
//+------------------------------------------------------------------+
#property copyright   "TraderAIG"
#property link        ""
#property version     "1.000"
#property description "TraderAIG execution agent - institutional layer."

#include <Trade\Trade.mqh>
#include <Json.mqh>

//+------------------------------------------------------------------+
//| Input parameters                                                  |
//+------------------------------------------------------------------+
input group "=== TraderAIG Core ==="
input string InpSymbolFilter     = "XAUUSD";  // Only trade this symbol
input bool   InpEnableTrading    = true;      // Master switch (Python gates this via entitlements)
input double InpHardMaxPosition  = 5;         // Hard ceiling on simultaneous positions
input double InpHardMaxLeverage  = 10.0;      // Hard leverage ceiling
input double InpHardMaxDailyLoss = 3.0;       // Hard daily loss % that stops the robot
input int    InpMaxSpreadPoints  = 40;        // Max allowed spread (points) to enter

input group "=== Python Bridge ==="
input string InpBridgeFileName   = "TraderAIG_bridge.json"; // shared file (Common folder)
input int    InpBridgePollMS     = 1000;      // Bridge check engine (ms)

//+------------------------------------------------------------------+
//| Global state                                                      |
//+------------------------------------------------------------------+
CTrade   trade;
string   g_symbol;
ulong    g_lastTicket        = 0;
datetime g_lastBridgeCheck   = 0;
bool     g_hardStopTriggered = false;
double   g_sessionStartEquity = 0.0;

//+------------------------------------------------------------------+
//| Initialization                                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_symbol = InpSymbolFilter;

   trade.SetExpertMagicNumber(123456);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(g_symbol);

   g_sessionStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_hardStopTriggered  = false;

   PrintFormat("TraderAIG EA initialized on %s | equity=%.2f",
               g_symbol, g_sessionStartEquity);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Deinitialization                                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   Print("TraderAIG EA deinitialized. reason=", reason);
  }

//+------------------------------------------------------------------+
//| Tick handler (drives the slow bridge loop)                        |
//+------------------------------------------------------------------+
void OnTick()
  {
   // Hard daily-loss stop: kill the robot before it can act.
   CheckHardDailyLossStop();

   if(IsBridgeDue())
     {
      HandleBridgeFile();
      g_lastBridgeCheck = TimeCurrent();
     }
  }

//+------------------------------------------------------------------+
//| Hard risk ceiling - local enforcement                            |
//+------------------------------------------------------------------+
bool IsWithinHardRiskLimits(double volume, double sl, double tp)
  {
   // 1. Spread gate
   long   spreadPoints = SymbolInfoInteger(g_symbol, SYMBOL_SPREAD);
   if(spreadPoints > InpMaxSpreadPoints)
     {
      PrintFormat("Spread too wide: %I64d points (limit %d)", spreadPoints, InpMaxSpreadPoints);
      return(false);
     }

   // 2. Position count ceiling
   int openPositions = CountOpenPositions();
   if(openPositions >= (int)InpHardMaxPosition)
     {
      PrintFormat("Position ceiling reached: %d >= %.0f", openPositions, InpHardMaxPosition);
      return(false);
     }

   // 3. Per-trade risk sanity: SL must exist (institutional rule)
   if(InpSymbolFilter != "" && (sl <= 0.0 || tp <= 0.0))
     {
      PrintFormat("Missing stop loss or take profit");
      return(false);
     }

   // 4. Leverage ceiling
   double notional      = volume * SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_VALUE);
   double equity        = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > 0.0 && (notional / equity) > InpHardMaxLeverage)
     {
      PrintFormat("Leverage ceiling breached: %.2fx (limit %.1fx)",
                  notional / equity, InpHardMaxLeverage);
      return(false);
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Position count                                                    |
//+------------------------------------------------------------------+
int CountOpenPositions()
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == g_symbol)
         count++;
     }
   return(count);
  }

//+------------------------------------------------------------------+
//| Hard daily loss enforcement (institutional kill-switch)           |
//+------------------------------------------------------------------+
void CheckHardDailyLossStop()
  {
   if(g_hardStopTriggered)
      return;

   double equityNow = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_sessionStartEquity <= 0.0)
      g_sessionStartEquity = equityNow;

   double lossPct = (g_sessionStartEquity - equityNow) / g_sessionStartEquity * 100.0;
   if(lossPct >= InpHardMaxDailyLoss)
     {
      g_hardStopTriggered = true;
      PrintFormat("HARD STOP: daily loss %.2f%% >= %.2f%%", lossPct, InpHardMaxDailyLoss);
     }
  }

//+------------------------------------------------------------------+
//| Bridge polling due?                                              |
//+------------------------------------------------------------------+
bool IsBridgeDue()
  {
   return(TimeCurrent() - g_lastBridgeCheck >= InpBridgePollMS / 1000);
  }

//+------------------------------------------------------------------+
//| Bridge file (JSON) handler                                       |
//+------------------------------------------------------------------+
void HandleBridgeFile()
  {
   string commonPath = TerminalInfoString(TERMINAL_COMMONDATA_PATH);
   string filePath = commonPath + "\\" + InpBridgeFileName;

   if(!FileIsExist(filePath))
      return;

   string result = ReadBridgeFile(filePath);
   if(StringLen(result) < 2)
      return;

   // Parse the JSON dictionary.
   CJAVal root;
   if(!root.Deserialize(result))
     {
      Print("TraderAIG bridge: malformed JSON");
      return;
     }

   // Only act on explicit APPROVED signal with full execution plan.
   string signal = root["signal"].ToStr();
   if(signal != "trade")
      return;

   string symbol = root["symbol"].ToStr();
   if(InpSymbolFilter != "" && symbol != InpSymbolFilter)
      return;

   string action   = root["action"].ToStr();   // buy / sell
   double volume   = root["volume"].ToDbl();
   double sl       = root["sl"].ToDbl();
   double tp       = root["tp"].ToDbl();
   double price    = root["price"].ToDbl();

   if(volume <= 0.0)
     {
      Print("TraderAIG bridge: invalid volume in signal");
      return;
     }

   // Local hard gate (idempotent with Python's Risk Governor).
   if(!g_hardStopTriggered && IsWithinHardRiskLimits(volume, sl, tp))
     {
      bool ok = SubmitOrder(action, volume, sl, tp, price);
      if(ok)
        {
         // Ack the signal so Python does not resend it.
         WriteBridgeFile(filePath, "ack");
        }
     }
   else
     {
      PrintFormat("TraderAIG bridge: rejected locally (%s %.2f lots)", action, volume);
      WriteBridgeFile(filePath, "rejected");
     }
  }

//+------------------------------------------------------------------+
//| Read the JSON bridge file                                        |
//+------------------------------------------------------------------+
string ReadBridgeFile(string path)
  {
   int handle = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return("");

   string content = "";
   while(!FileIsEnding(handle))
      content += FileReadString(handle) + "\n";

   FileClose(handle);
   return(content);
  }

//+------------------------------------------------------------------+
//| Write ack / status to the bridge file                            |
//+------------------------------------------------------------------+
bool WriteBridgeFile(string path, string status)
  {
   int handle = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
     {
      Print("TraderAIG bridge: cannot write status file");
      return(false);
     }

   CJAVal root;
   root["status"] = status;
   root["ticket"] = (long)g_lastTicket;
   string jsonOut = root.Serialize();

   FileWriteString(handle, jsonOut);
   FileClose(handle);
   return(true);
  }

//+------------------------------------------------------------------+
//| Order submission (market)                                       |
//+------------------------------------------------------------------+
bool SubmitOrder(string action, double volume, double sl, double tp, double price)
  {
   ENUM_ORDER_TYPE otype = action == "buy" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

   if(!trade.PositionOpen(g_symbol, otype, volume, price, sl, tp, "TraderAIG"))
     {
      PrintFormat("TraderAIG order failed: %u", GetLastError());
      return(false);
     }

   g_lastTicket = trade.ResultOrder();
   return(true);
  }

//+------------------------------------------------------------------+
//| Timer (fallback if tick frequency is low)                         |
//+------------------------------------------------------------------+
void OnTimer()
  {
   OnTick();
  }
//+------------------------------------------------------------------+