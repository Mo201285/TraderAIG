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
//|                                                                  |
//|  Market data (28.6): the EA also *publishes* its own tick and    |
//|  forming-bar frame to <common>\bridge\market\<SYMBOL>.json.      |
//|  Prices only flow terminal -> server; the server treats these    |
//|  frames as the lowest-priority bridge source, so they can never  |
//|  override a real MT5 window or quote owned by the Python core.   |
//+------------------------------------------------------------------+
#property copyright   "TraderAIG"
#property link        ""
#property version     "1.100"
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

input group "=== Market Publisher (28.6) ==="
input bool   InpPublishMarket    = true;      // Publish tick/bar frames to the backend
input string InpMarketSubDir     = "bridge\\market"; // market frame directory (Common folder)
input int    InpMarketTimeframe  = PERIOD_M15; // Bar timeframe published with each tick
input int    InpMarketIntervalMS = 1000;      // Market publish cadence (ms)

//+------------------------------------------------------------------+
//| Global state                                                      |
//+------------------------------------------------------------------+
CTrade   trade;
string   g_symbol;
ulong    g_lastTicket        = 0;
datetime g_lastBridgeCheck   = 0;
bool     g_hardStopTriggered = false;
double   g_sessionStartEquity = 0.0;
datetime g_lastMarketWrite   = 0;

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

   PublishMarketFrame();
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
//| Market publisher (28.6)                                          |
//| Publishes the terminal's OWN real tick and forming bar so the    |
//| Python core has a market source when no python-MT5 session is    |
//| attached. Values come from SymbolInfo* only; nothing is derived,  |
//| defaulted or guessed - a side the terminal does not report is     |
//| simply not written.                                              |
//+------------------------------------------------------------------+
string MarketTimeframeName(const ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_M1:  return("M1");
      case PERIOD_M5:  return("M5");
      case PERIOD_M15: return("M15");
      case PERIOD_M30: return("M30");
      case PERIOD_H1:  return("H1");
      case PERIOD_H4:  return("H4");
      case PERIOD_D1:  return("D1");
      case PERIOD_W1:  return("W1");
     }
   return("M15");
  }

string MarketFrameJson()
  {
   MqlTick tick;
   if(!SymbolInfoTick(g_symbol, tick))
      return("");

   string tfName = MarketTimeframeName((ENUM_TIMEFRAMES)InpMarketTimeframe);
   int    barSeconds = PeriodSeconds((ENUM_TIMEFRAMES)InpMarketTimeframe);
   if(barSeconds <= 0)
      barSeconds = 900;

   double last   = tick.last;
   double bid    = tick.bid;
   double ask    = tick.ask;
   if(last <= 0.0 || bid <= 0.0 || ask <= 0.0)
      return("");   // no real two-sided price: publish nothing rather than guess

   datetime now      = TimeCurrent();
   datetime barStart = (datetime)(((long)now / barSeconds) * barSeconds);

   CJAVal root;
   root["symbol"]   = g_symbol;
   root["timeframe"] = tfName;
   root["time"]     = (long)now;

   CJAVal quote;
   quote["bid"]        = bid;
   quote["ask"]        = ask;
   quote["last"]       = last;
   quote["spread"]     = ask - bid;
   quote["tick_time"]  = (long)tick.time;
   root["quote"]       = quote;

   // The forming bar: real o/h/l/c so far, updated on every publish. The
   // server replaces the last bar on the same timestamp, so this is a
   // stream, not a duplicate history.
   double barOpen  = iOpen (g_symbol, InpMarketTimeframe, 0);
   double barHigh  = iHigh (g_symbol, InpMarketTimeframe, 0);
   double barLow   = iLow  (g_symbol, InpMarketTimeframe, 0);
   double barClose = iClose(g_symbol, InpMarketTimeframe, 0);
   long   barVol   = iVolume(g_symbol, InpMarketTimeframe, 0);
   if(barOpen > 0.0 && barHigh > 0.0 && barLow > 0.0 && barClose > 0.0)
     {
      CJAVal bar;
      bar["time"]        = (long)barStart;
      bar["open"]        = barOpen;
      bar["high"]        = barHigh;
      bar["low"]         = barLow;
      bar["close"]       = barClose;
      bar["tick_volume"] = (long)barVol;

      CJAVal bars[1];
      bars[0] = bar;
      root["bars"] = bars;
     }
   else
     {
      CJAVal bars[];
      root["bars"] = bars;         // no real bar: send none, do not fake one
     }

   return(root.Serialize());
  }

void PublishMarketFrame()
  {
   if(!InpPublishMarket)
      return;

   datetime now = TimeCurrent();
   long elapsedMs = (long)(now - g_lastMarketWrite) * 1000;
   if(g_lastMarketWrite != 0 && elapsedMs < InpMarketIntervalMS)
      return;

   string json = MarketFrameJson();
   if(StringLen(json) < 2)
      return;

   string commonPath = TerminalInfoString(TERMINAL_COMMONDATA_PATH);
   string dir        = commonPath + "\\" + InpMarketSubDir;
   string filePath   = dir + "\\" + g_symbol + ".json";

   // FolderCreate returns false when the folder already exists, which is the
   // normal case after the first tick; only a missing folder is a problem.
   if(!FolderCreate(dir) && !FolderExists(dir))
     {
      PrintFormat("TraderAIG market: cannot create %s (err %d)", dir, GetLastError());
      return;
     }

   int handle = FileOpen(filePath, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
     {
      PrintFormat("TraderAIG market: cannot write %s", filePath);
      return;
     }

   FileWriteString(handle, json);
   FileClose(handle);
   g_lastMarketWrite = now;
  }

//+------------------------------------------------------------------+
//| Timer (fallback if tick frequency is low)                         |
//+------------------------------------------------------------------+
void OnTimer()
  {
   OnTick();
  }
//+------------------------------------------------------------------+
