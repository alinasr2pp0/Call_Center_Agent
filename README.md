# Call Center Agent

مركز اتصال ذكي: بوابة للعملاء + لوحة تحكم للإدارة، قاعدة البيانات **SQLite** (ملف واحد، بدون أي إعداد).
An AI-assisted call center: customer portal + admin dashboard, backed by **SQLite** (a single file, zero setup).

## التشغيل السريع / Quick start

```bash
# Linux / macOS
./scripts/run.sh
# Windows
scripts\run.bat
```

أو يدويًا / or manually:

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp .env.example .env                                    # اختياري / optional
cd backend && python run.py
```

- بوابة العميل / Customer portal: http://127.0.0.1:8000/
- لوحة الإدارة / Admin dashboard: http://127.0.0.1:8000/admin
- توثيق الـ API / API docs: http://127.0.0.1:8000/docs

عند أول تشغيل يتم إنشاء حساب `superadmin`. إن لم تضع `SUPERADMIN_PASSWORD` في `.env` تُطبع كلمة مرور عشوائية **مرة واحدة** في نافذة التشغيل.
On first start a `superadmin` account is created; without `SUPERADMIN_PASSWORD` a random password is printed **once** in the console.

قاعدة البيانات تُنشأ تلقائيًا في `data/call_center.db` مع 4 شخصيات ومقالات معرفة تجريبية (`SEED_SAMPLE_KB=false` لإيقافها).

## كيف يعمل / How it works

1. العميل يسجّل حسابًا ويكتب (أو يسجّل صوتيًا) مشكلته ويختار أسلوب الرد (الشخصية).
2. الوكيل يبحث في قاعدة المعرفة (BM25 + تطبيع عربي ولهجة مصرية). إذا وُجد حل واثق يُرسل، وإلا يُصعَّد التذكرة لموظف بشري.
3. اختياريًا: بـ **OpenRouter** تتم إعادة صياغة الحل بأسلوب الشخصية، وبـ **Groq** الرسائل الصوتية والرد المنطوق (STT/TTS) فقط، وبـ Tavily بحث إنترنت احتياطي، وبـ Vonage مكالمة متابعة (اضغط 1 = تم الحل، 2 = لم تُحل).
4. اللوحة تعرض التذاكر والمقاييس (FCR، التصعيد، الوصول للعميل...) محسوبة من بيانات حقيقية فقط.

بدون أي مفاتيح خارجية يعمل النظام بالكامل بالبحث في قاعدة المعرفة (الرد الصوتي ومكالمات المتابعة تحتاج مفاتيحها).

### مزوّدو الذكاء الاصطناعي / AI providers

| الوظيفة | المزوّد | المتغيرات |
|---|---|---|
| النموذج اللغوي (إعادة صياغة الحل، بحث الويب) | OpenRouter | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (اختياري: `OPENROUTER_BASE_URL`, `OPENROUTER_REFERER`) |
| الصوت: تحويل الكلام لنص + النص لكلام | Groq | `GROQ_API_KEY`, `WHISPER_MODEL`, `STT_LANGUAGE`, `GROQ_TTS_MODEL`, `GROQ_TTS_VOICE` |
| بحث الإنترنت الاحتياطي | Tavily | `TAVILY_API_KEY` (يحتاج `OPENROUTER_API_KEY` أيضًا) |

المفتاحان مستقلان: يمكنك تفعيل الصوت فقط (Groq) أو النموذج اللغوي فقط (OpenRouter). الحالتان تظهران في `GET /health` (`llm_configured`, `speech_configured`).
> ترقية من إصدار سابق: `GROQ_MODEL` لم يعد مستخدمًا؛ استبدله بـ `OPENROUTER_API_KEY` و`OPENROUTER_MODEL`.

## المستندات / Documents

من لوحة الإدارة › قاعدة المعرفة › «رفع مستند» (للأدمن والسوبر أدمن؛ الـ agent يعرض فقط).

- الأنواع: PDF و DOCX و TXT و MD، حتى 10 ميجا للملف. الملفات الممسوحة ضوئيًا (صور) أو المحمية بكلمة مرور غير مدعومة (لا يوجد OCR).
- يُستخرج النص ويُنظَّف ويُقسَّم إلى مقاطع (~80 كلمة) وكل مقطع يصبح مقالة في قاعدة المعرفة، فيجدها البحث الكلمي والدلالي.
- الملف نفسه لا يُرفع مرتين (يُرفض بخطأ 409). الملف الأصلي لا يُحفظ، النص فقط.
- المقاطع تُدار عبر المستند (حذف المستند يحذف مقاطعه) ولا تُعدَّل واحدًا واحدًا. زر «تصفير البيانات» لا يمس المستندات.
- مسارات الـ API: `GET/POST /admin/documents` و `DELETE /admin/documents/{id}`.

## البحث الدلالي (اختياري) / Semantic search (optional)

افتراضيًا البحث بالكلمات (BM25). لتفعيل البحث بالمعنى محليًا:

```bash
pip install -r backend/requirements-ai.txt
# في .env:
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=intfloat/multilingual-e5-small     # أو BAAI/bge-m3
VECTOR_STORE=sqlite                                 # أو qdrant (+ QDRANT_URL)
RERANKER_ENABLED=true                               # اختياري
```

- يُنزَّل النموذج من Hugging Face في أول تشغيل ثم يعمل بدون إنترنت. الفهرسة تتم في الخلفية، والنظام يعمل بـ BM25 حتى تنتهي.
- المتجهات تُخزَّن في جدول `kb_embeddings` داخل ملف SQLite نفسه، أو في Qdrant إن اخترته (يُنشأ الـ collection تلقائيًا).
- عند إضافة/تعديل/حذف مقال تُحدَّث المتجهات تلقائيًا (فقط ما تغيّر). الحالة: `GET /admin/search/status` وإعادة الفهرسة: `POST /admin/search/reindex`.
- النتيجة = دمج ترتيب BM25 مع ترتيب المتجهات (RRF)، ثم Rerank اختياري بنموذج cross-encoder.
- لو تعذّر تحميل النموذج أو أي مكتبة يستمر النظام بـ BM25 دون توقف (الحالة `error` في `/health`).
- **اضبط `VECTOR_MIN_SCORE` و`RERANK_MIN_SCORE` على بياناتك**: قيم التشابه تختلف من نموذج لآخر.

## الأدوار / Roles

| الدور | الصلاحيات |
|---|---|
| `superadmin` | كل شيء + إدارة الموظفين |
| `admin` | المقاييس، قاعدة المعرفة، العملاء، الشخصيات، تصفير البيانات |
| `agent` | عرض الإحصائيات والتذاكر وقاعدة المعرفة (قراءة فقط) |

## الاختبارات / Tests

```bash
cd backend
python -m unittest discover -s tests -v                          # كلمات مفتاحية فقط
EMBEDDING_PROVIDER=local python -m unittest discover -s tests -v  # البحث الهجين (بنماذج وهمية سريعة + Qdrant وهمي)
```

## هيكل المشروع / Layout

```
backend/app/agent/     الوكيل: القرار (service) · النصوص (prompts) · النموذج اللغوي OpenRouter (llm)
                       · الصوت Groq (speech) · التذاكر (tickets) · مكالمات المتابعة (followup)
backend/app/rag/       الاسترجاع: knowledge (المدخل) · bm25 · text · retrieval (RRF + rerank)
                       · documents (رفع الملفات) · semantic/ (embeddings + المخازن)
backend/app/           routers · models · schemas · config · database · core (أمان، مقاييس) · services/kpi
backend/tests/    اختبارات
frontend/         index.html (العميل) و admin.html (الإدارة)
data/             ملف SQLite والمفتاح السري (يُنشآن تلقائيًا)
scripts/          run.sh / run.bat
```

## ملاحظات أمنية / Security notes

- كلمات المرور PBKDF2-SHA256، رموز JWT، وحد لمحاولات الدخول الفاشلة.
- روابط Vonage الموقّعة بـ HMAC. لا ترفع `.env` أو `data/` أو `private.key` إلى Git (مستثناة في `.gitignore`).
- للإنتاج ضع التطبيق خلف HTTPS.
