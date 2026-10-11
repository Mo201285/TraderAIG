للوصول لـ LIVE الحقيقي تحتاج:

1. **MT5 Live Account**
   - حساب حقيقي أو حيز تجريبي فعّال في MetaTrader 5
   - بيانات الدخول (Server, Login, Password)
   - توصيل MT5 Bridge (جسر Python-MT5) مع الربط الصحيح

2. **أو ربط CEX (Binance/Bybit/OKX)**
   - API Keys مع صلاحيات Trade فقط (لا Withdrawal)
   - IP Allowlist
   - Network/Testnet للتجربة أولاً ثم Live

3. **تهيئة البيئة**
   - تحديث .env: إعدادات الوسيط الحي
   - تفعيل reconciliation مع Venue الفعلي
   - ضبط Risk Policy لكل حساب
   - ربط TradingAccount → Provider → Policy → StrategyBinding

4. **تحقق قبل LIVE**
   - Paper trading مستقر لفترة كافية
   - جميع البوابات تمر (Governance/Risk/Execution)
   - Backtest + WFO + Monte Carlo + Stress Test للاسترراتيجية المراد تفعيلها
   - Kill Switch جاهز ومختبر

5. **متطلبات تقنية**
   - MT5 مفتوح ومتصل (لو MT5)
   - مفاتيح API آمنة (Key/Secret) مخزنة محليًا فقط
   - عدم تعريض :8000 للإنترنت (يبقى localhost)
   - مراقبة النظام + Logs

ملاحظات حالية:
- reconciliation = Degraded الآن لأنه لا يوجد venue حي متصل
- عند توصيل venue حي وصحيح، سيصبح reconciliation Healthy
- النظام جاهز من ناحية البنية (Gates/Provenance/Audit) للانتقال لـ Live بأمان
