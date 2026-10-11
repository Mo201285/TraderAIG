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

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
input group "=== Market Publisher (28.6) ==="
input bool   InpPublishMarket    = true;      // Publish tick/bar frames to the backend
input string InpMarketSubDir     = "market";  // <Common>\market\ must match the server's bridge market dir
input int    InpMarketTimeframe  = PERIOD_M15; // Bar timeframe published with each tick
input int    InpMarketIntervalMS = 1000;      // Market publish cadence (ms)

//+------------------------------------------------------------------+
//| Session schedules (weekend close windows)                        |
//| python-MT5 does not expose SymbolInfoSessionTrade, so the        |
//| backend cannot work out when each symbol actually stops trading  |
//| on Friday. The terminal can, authoritatively. This publishes the |
//| terminal's own weekly trade schedule per symbol; the server uses |
//| it to place a close window and, where a symbol has no readable  |
//| schedule, treats it as unreadable rather than guessing.          |
//+------------------------------------------------------------------+
input group "=== Session Publisher ==="
input bool   InpPublishSessions  = true;      // Publish per-symbol trading schedules
input string InpSessionsSubDir   = "sessions";// <Common>\sessions\sessions.json
input int    InpSessionsIntervalMS = 300000;  // Schedule publish cadence (ms)

//+------------------------------------------------------------------+
//| Global state                                                      |
//+------------------------------------------------------------------+
CTrade   trade;
string   g_symbol;
// The market publisher follows the CHART's own symbol, not the trading
// filter. `InpSymbolFilter` is a decision about what to trade; the data this
// EA publishes must be the symbol the terminal is actually streaming here.
// Conflating the two was silent: on a BTCUSD chart the publisher went looking
// for XAUUSD ticks, found none, and wrote nothing at all while looking
// perfectly healthy in the Experts log.
string   g_marketSymbol;
ulong    g_lastTicket        = 0;
datetime g_lastBridgeCheck   = 0;
bool     g_hardStopTriggered = false;
double   g_sessionStartEquity = 0.0;
datetime g_lastMarketWrite   = 0;
bool     g_marketWriteReported = false;   // one diagnostic per session, not one per tick
datetime g_lastSessionsWrite = 0;
bool     g_sessionsWriteReported = false;
int      g_sessionsSymbolCount = -1;      // -1 = not reported yet this session

//+------------------------------------------------------------------+
//| Initialization                                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_symbol = InpSymbolFilter;
   g_marketSymbol = _Symbol;

   trade.SetExpertMagicNumber(123456);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(g_symbol);

   g_sessionStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_hardStopTriggered  = false;

   PrintFormat("TraderAIG EA initialized on %s | equity=%.2f | publishing %s",
               g_symbol, g_sessionStartEquity, g_marketSymbol);
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
   PublishSessionSchedules();
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
      case PERIOD_M1:
         return("M1");
      case PERIOD_M5:
         return("M5");
      case PERIOD_M15:
         return("M15");
      case PERIOD_M30:
         return("M30");
      case PERIOD_H1:
         return("H1");
      case PERIOD_H4:
         return("H4");
      case PERIOD_D1:
         return("D1");
      case PERIOD_W1:
         return("W1");
     }
// Unsupported: return nothing so the frame is not published under a name
// the server never asked for (it would reject it anyway) and this EA never
// claims to be sending a timeframe it is not sending.
   return("");
  }

//+------------------------------------------------------------------+
//| JsonNumber                                                        |
//| A JSON number, always with a decimal point so a consumer never   |
//| has to guess between int and float. DoubleToString always uses  |
//| '.', so no locale hazard.                                        |
//+------------------------------------------------------------------+
string JsonNumber(const double value)
  {
   if(value == 0.0)
      return("0.0");
   return(DoubleToString(value, 8));
  }

//+------------------------------------------------------------------+
//| JsonInt                                                           |
//| A JSON integer. This terminal build has no LongToString, and     |
//| IntegerToString takes an int, which overflows on a real epoch    |
//| second. DoubleToString with 0 decimals is exact for anything     |
//| under 2^53, so epoch seconds and tick volumes print correctly.   |
//+------------------------------------------------------------------+
string JsonInt(const long value)
  {
   return(DoubleToString((double)value, 0));
  }

//+------------------------------------------------------------------+
//| MarketFrameJson                                                   |
//| The frame is built as text on purpose: the Json.mqh shipped with |
//| this terminal only supports flat key/value pairs (no nested     |
//| objects, no arrays), and this frame needs a quote object and a  |
//| bars array. The exact shape is the server's:                   |
//|   {symbol, timeframe, time, quote:{bid,ask,last,spread,         |
//|    tick_time}, bars:[{time,open,high,low,close,tick_volume}]}   |
//+------------------------------------------------------------------+
string MarketFrameJson()
  {
   MqlTick tick;
   if(!SymbolInfoTick(g_marketSymbol, tick))
      return("");

   string tfName = MarketTimeframeName((ENUM_TIMEFRAMES)InpMarketTimeframe);
   if(StringLen(tfName) == 0)
      return("");   // unsupported timeframe: publish nothing rather than name another

   int barSeconds = PeriodSeconds((ENUM_TIMEFRAMES)InpMarketTimeframe);
   if(barSeconds <= 0)
      return("");   // no real bar length: no bar time can be derived honestly

   double last = tick.last;
   double bid  = tick.bid;
   double ask  = tick.ask;
// Two real sides is what makes a quote usable. `last` is NOT part of that
// test: plenty of real venues (every crypto CFD here, for one) report no
// last trade at all and only ever fill bid/ask. Gating on `last > 0` meant
// the publisher stayed silent on exactly the symbol the operator trades.
// The server derives last from the mid when the terminal has no last, so
// nothing is invented here.
   if(bid <= 0.0 || ask <= 0.0)
      return("");   // no real two-sided price: publish nothing rather than guess
   if(ask < bid)
      return("");   // crossed book: not a real market state

   datetime now      = TimeCurrent();
   datetime barStart = (datetime)(((long)now / barSeconds) * barSeconds);

   string json = "{";
   json += "\"symbol\":\"" + g_marketSymbol + "\",";
   json += "\"timeframe\":\"" + tfName + "\",";
   json += "\"time\":" + JsonInt((long)now) + ",";
// When the venue reports no last trade, the mid of the two real sides is
// published instead -- the same rule `execution/mt5_adapter.py` already
// applies to this terminal's ticks, so nothing downstream has to invent a
// price of its own. `last_source` says which it is, so a consumer can tell
// a traded last from a derived mid; the frame is self-describing rather
// than quietly presenting a mid as a trade.
   bool lastIsTrade = (last > 0.0);
   json += "\"quote\":{";
   json += "\"bid\":"       + JsonNumber(bid) + ",";
   json += "\"ask\":"       + JsonNumber(ask) + ",";
   json += "\"last\":"      + JsonNumber(lastIsTrade ? last : (bid + ask) / 2.0) + ",";
   json += "\"last_source\":\"" + (lastIsTrade ? "trade" : "mid") + "\",";
   json += "\"spread\":"    + JsonNumber(ask - bid) + ",";
   json += "\"tick_time\":" + JsonInt((long)tick.time);
   json += "}";

// The forming bar: real o/h/l/c so far, re-sent on every publish. The
// server replaces the bar with the same timestamp, so this is a stream,
// not duplicate history.
   double barOpen  = iOpen(g_marketSymbol, (ENUM_TIMEFRAMES)InpMarketTimeframe, 0);
   double barHigh  = iHigh(g_marketSymbol, (ENUM_TIMEFRAMES)InpMarketTimeframe, 0);
   double barLow   = iLow(g_marketSymbol, (ENUM_TIMEFRAMES)InpMarketTimeframe, 0);
   double barClose = iClose(g_marketSymbol, (ENUM_TIMEFRAMES)InpMarketTimeframe, 0);
   long   barVol   = iVolume(g_marketSymbol, (ENUM_TIMEFRAMES)InpMarketTimeframe, 0);
   if(barOpen > 0.0 && barHigh > 0.0 && barLow > 0.0 && barClose > 0.0)
     {
      json += ",\"bars\":[{";
      json += "\"time\":"        + JsonInt((long)barStart) + ",";
      json += "\"open\":"        + JsonNumber(barOpen) + ",";
      json += "\"high\":"        + JsonNumber(barHigh) + ",";
      json += "\"low\":"         + JsonNumber(barLow) + ",";
      json += "\"close\":"       + JsonNumber(barClose) + ",";
      json += "\"tick_volume\":" + JsonInt(barVol);
      json += "}]";
     }
// else: no real bar, so no `bars` key at all. The server treats a frame
// without bars as a quote-only frame; it never invents a bar.

   json += "}";
   return(json);
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
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

// MQL5 will not write outside its sandbox, and with FILE_COMMON it resolves
// a RELATIVE path against the shared root `<TERMINAL_COMMONDATA_PATH>\Files`.
// A live attach proved both halves of that: an absolute path under Common
// returned err 5002 while a probe file in the common root wrote fine, and
// FolderCreate on that absolute path failed the same way. So: relative here,
// `<common>\Files\market\<SYMBOL>.json` on disk, and the server points
// MT5_COMMON_DATA at `<common>\Files`.
   string commonPath = TerminalInfoString(TERMINAL_COMMONDATA_PATH);
   string relDir     = InpMarketSubDir;                 // resolved under Common\Files
   string dir        = commonPath + "\\Files\\" + relDir;
   string filePath   = relDir + "\\" + g_marketSymbol + ".json";

   bool dirMade = FolderCreate(relDir, FILE_COMMON);
   int  dirErr  = GetLastError();

   int handle = FileOpen(filePath, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      int err = GetLastError();
      // Say exactly once per session why the publisher is dead, and whether
      // the shared root itself is writable: "cannot write" with no cause is
      // what made the first live attach pointless.
      if(!g_marketWriteReported)
        {
         g_marketWriteReported = true;
         int probe = FileOpen("TraderAIG_probe.tmp",
                              FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
         bool rootWritable = (probe != INVALID_HANDLE);
         if(probe != INVALID_HANDLE)
            FileClose(probe);
         PrintFormat("TraderAIG market: cannot write %s (err %d) | common=%s | "
                     "dirCreated=%d dirErr=%d | commonRootWritable=%d",
                     filePath, err, commonPath, (int)dirMade, dirErr,
                     (int)rootWritable);
        }
      // Throttle the failure too, or a bad path spams the log on every tick.
      g_lastMarketWrite = now;
      return;
     }

   FileWriteString(handle, json);
   FileClose(handle);
   g_lastMarketWrite = now;
  }

//+------------------------------------------------------------------+
//| SessionJsonFor                                                    |
//| The terminal's own weekly trade schedule for one symbol.         |
//|                                                                  |
//|   {"symbol":"EURUSD","mode":4,"sessions":[[5,36000,82800],       |
//|                                          [6,0,10]]}             |
//|                                                                  |
//| Each entry is [weekday, from_seconds, to_seconds] in the        |
//| terminal's own (server) day, and mode is SYMBOL_TRADE_MODE.     |
//| Hand-built text like the market frame: Json.mqh on this terminal |
//| supports no nested objects or arrays.                            |
//|                                                                  |
//| Returns "" when the symbol reports no session at all. An        |
//| unreadable schedule and a zero-length one are not the same      |
//| thing, and the server acts differently on each -- so "" must     |
//| mean the former and must never be smoothed into the latter.      |
//+------------------------------------------------------------------+
string SessionJsonFor(const string symbol)
  {
   string sessions = "";

   for(int day = 0; day <= 6; day++)
     {
      for(int idx = 0; idx < 8; idx++)
        {
         datetime from = 0, to = 0;
         if(!SymbolInfoSessionTrade(symbol, (ENUM_DAY_OF_WEEK)day, idx, from, to))
            break;

         if(sessions == "")
            sessions += "[";
         else
            sessions += ",";

         sessions += "[" + IntegerToString(day) + ","
                     + IntegerToString((int)from) + ","
                     + IntegerToString((int)to) + "]";
        }
     }

   if(sessions == "")
      return("");

   long mode = SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   return("{\"symbol\":\"" + symbol + "\",\"mode\":" + JsonInt(mode)
          + ",\"sessions\":" + sessions + "]}");
  }

//+------------------------------------------------------------------+
//| PublishSessionSchedules                                           |
//| One file for the whole terminal rather than one per symbol: the  |
//| market watch of a live account runs to dozens of symbols, and    |
//| writing each of them on a timer would be dozens of file creates  |
//| to deliver one document the server reads in a single read.       |
//|                                                                  |
//| Market Watch is the set the operator actually has on screen and  |
//| it is bounded. The chart symbol is forced in as well, so the     |
//| schedule for whatever this EA is about to trade cannot be missing |
//| merely because nobody watched it.                                 |
//|                                                                  |
//| The chart symbol is forced in, and it is the MARKET symbol: the |
//| trading-filter symbol is a trading decision, and publishing a   |
//| schedule for a symbol nobody is charting is the attach defect   |
//| the publisher tests exist to catch, one function over.          |
//|                                                                  |
//| An empty symbol set is still published. "Attached, and I read no |
//| schedules" is a real and different state from "not attached",    |
//| and the weekend rule fails closed on both -- but only one of    |
//| them is something the operator can fix.                          |
//+------------------------------------------------------------------+
void PublishSessionSchedules()
  {
   if(!InpPublishSessions)
      return;

   datetime now = TimeCurrent();
   if(g_lastSessionsWrite != 0 &&
      (long)(now - g_lastSessionsWrite) * 1000 < InpSessionsIntervalMS)
      return;

   int    total   = SymbolsTotal(false);   // Market Watch
   string json    = "{\"server_time\":" + JsonInt((long)now) + ",\"symbols\":{";
   int    written = 0;

   for(int i = 0; i < total; i++)
     {
      string entry = SessionJsonFor(SymbolName(i, false));
      if(StringLen(entry) < 2)
         continue;
      if(written > 0)
         json += ",";
      json += entry;
      written++;
     }

   // The chart symbol only. The traded symbol is deliberately absent: a schedule
   // for a symbol this EA would trade but is not charting is still worth having,
   // but it is read from Market Watch, and forcing InpSymbolFilter in here would
   // publish a symbol on whose chart nothing is running.
   string forced[1] = {g_marketSymbol};
   for(int f = 0; f < 1; f++)
     {
      if(StringLen(forced[f]) == 0)
         continue;
      if(StringFind(json, "{\"symbol\":\"" + forced[f] + "\"", 0) >= 0)
         continue;
      string entry = SessionJsonFor(forced[f]);
      if(StringLen(entry) < 2)
         continue;
      if(written > 0)
         json += ",";
      json += entry;
      written++;
     }

   json += "}}";

   bool dirMade = FolderCreate(InpSessionsSubDir, FILE_COMMON);
   string filePath = InpSessionsSubDir + "\\sessions.json";

   int handle = FileOpen(filePath, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      int err = GetLastError();
      if(!g_sessionsWriteReported)
        {
         g_sessionsWriteReported = true;
         PrintFormat("TraderAIG sessions: cannot write %s (err %d) | dirCreated=%d",
                     filePath, err, (int)dirMade);
        }
      g_lastSessionsWrite = now;
      return;
     }

   FileWriteString(handle, json);
   FileClose(handle);
   g_lastSessionsWrite = now;

   if(g_sessionsSymbolCount != written)
     {
      g_sessionsSymbolCount = written;
      PrintFormat("TraderAIG sessions: published %d of %d market-watch symbols",
                  written, total);
     }
  }

//+------------------------------------------------------------------+
//| Timer (fallback if tick frequency is low)                         |
//+------------------------------------------------------------------+
void OnTimer()
  {
   OnTick();
  }
//+------------------------------------------------------------------+
