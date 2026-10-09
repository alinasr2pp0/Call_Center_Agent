"""First-run data: the four personas, a few sample KB articles, and the first superadmin."""
from __future__ import annotations

import logging
import secrets

from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import hash_password
from app.models import KBArticle, Persona, StaffUser

logger = logging.getLogger("call_center")

PERSONAS = [
    dict(name="سارة", role="مساعدة ودودة", is_default=True, verbosity="medium", max_words=110,
         description="أسلوب ودود وبسيط بالعامية المصرية",
         tone="تكلمي بالعامية المصرية بأسلوب ودود ومطمئن، وابدئي بتعاطف قصير مع العميل ثم اشرحي الحل خطوة بخطوة."),
    dict(name="أحمد", role="مختص فني", is_default=False, verbosity="short", max_words=80,
         description="إجابات فنية مختصرة ومباشرة",
         tone="تكلم بلغة فنية مباشرة ومختصرة، رقّم الخطوات، وتجنب المقدمات الطويلة."),
    dict(name="نور", role="مستشارة رسمية", is_default=False, verbosity="medium", max_words=120,
         description="لغة عربية فصحى مهذبة ورسمية",
         tone="تحدثي بالعربية الفصحى المهذبة والرسمية، واستخدمي عبارات احترام مناسبة، وقدّمي الحل بترتيب منطقي واضح."),
    dict(name="كريم", role="مرشد مبسّط", is_default=False, verbosity="detailed", max_words=160,
         description="شرح مفصل ومبسط لغير المتخصصين",
         tone="اشرح كأنك تتحدث مع شخص لا يعرف شيئًا عن التقنية، بكلمات سهلة وأمثلة بسيطة وخطوات صغيرة جدًا."),
]

# (product, ticket_type, subject, description, resolution, priority, channel)
SAMPLE_KB = [
    ("إنترنت منزلي", "Technical issue", "الإنترنت بطيء جدًا",
     "سرعة الإنترنت أقل بكثير من السرعة المشترك فيها وصفحات الويب تفتح ببطء.",
     "أعد تشغيل الراوتر بفصله عن الكهرباء 30 ثانية ثم تشغيله. جرّب السرعة بكابل مباشر للتأكد أن المشكلة ليست من الواي فاي، "
     "وابتعد عن الأجهزة المسببة للتشويش. لو السرعة لم تتحسن بعد 10 دقائق من إعادة التشغيل سجّل رقم الخط لفحصه.",
     "Medium", "Phone"),
    ("إنترنت منزلي", "Technical issue", "الإنترنت مقطوع ولا يوجد اتصال",
     "لا يعمل الإنترنت نهائيًا ومؤشر الإنترنت في الراوتر أحمر أو مطفي.",
     "تأكد من توصيل كابل الخط الأرضي أو الفايبر جيدًا في الراوتر ومن وصول الكهرباء له. أعد تشغيل الراوتر وانتظر دقيقتين حتى يثبت "
     "مؤشر الإنترنت. إذا ظل المؤشر أحمر فقد يكون هناك انقطاع في المنطقة وسيتم فحص الخط.",
     "High", "Phone"),
    ("راوتر", "Technical issue", "نسيت كلمة سر الواي فاي",
     "العميل نسي كلمة مرور شبكة الواي فاي ويريد تغييرها.",
     "ادخل على صفحة الراوتر من المتصفح بالعنوان 192.168.1.1 باسم المستخدم وكلمة المرور المكتوبين خلف الجهاز، ثم اذهب إلى "
     "إعدادات الواي فاي وغيّر كلمة المرور واحفظ. وإن كنت غيّرت بيانات الدخول من قبل فاضغط زر Reset خلف الراوتر 10 ثوانٍ لإعادة ضبط المصنع.",
     "Low", "Chat"),
    ("راوتر", "Technical issue", "الواي فاي ضعيف في بعض الغرف",
     "إشارة الواي فاي ضعيفة أو تنقطع في الغرف البعيدة عن الراوتر.",
     "ضع الراوتر في مكان مرتفع ومفتوح وسط المنزل بعيدًا عن الحوائط السميكة والأجهزة الكهربائية. استخدم نطاق 2.4GHz للمسافات "
     "البعيدة و5GHz للقريبة، ويمكن استخدام مقوّي إشارة (Extender) للغرف البعيدة.",
     "Low", "Chat"),
    ("إنترنت منزلي", "Billing inquiry", "الفاتورة أعلى من المعتاد",
     "العميل لاحظ أن قيمة فاتورة هذا الشهر أعلى من الشهور السابقة.",
     "راجع تفاصيل الفاتورة من التطبيق في قسم الفواتير، وتأكد من عدم وجود استهلاك إضافي خارج الباقة أو خدمات مضافة أو رسوم تأخير. "
     "إذا وجدت بندًا لا تعرفه سجّل رقمه وسيتم مراجعته وتعديل الفاتورة عند ثبوت الخطأ.",
     "Medium", "Phone"),
    ("إنترنت منزلي", "Billing inquiry", "كيف أدفع الفاتورة",
     "العميل يسأل عن طرق دفع الفاتورة الشهرية.",
     "يمكنك دفع الفاتورة من التطبيق أو الموقع بالكارت البنكي أو المحفظة الإلكترونية، أو من خلال منافذ الدفع الإلكتروني ومكاتب الخدمة "
     "باستخدام رقم الخط. يصلك إشعار بتأكيد الدفع خلال دقائق.",
     "Low", "Chat"),
    ("باقة موبايل", "Billing inquiry", "الرصيد اتخصم بدون سبب",
     "تم خصم رصيد من الخط دون استخدام واضح.",
     "افحص الاستهلاك من كود الاستعلام أو التطبيق، وتأكد من إيقاف الاشتراكات والخدمات المضافة غير المطلوبة وتحديث الإنترنت في الخلفية. "
     "يمكنك إيقاف أي اشتراك مفعّل من قسم الخدمات في التطبيق.",
     "Medium", "Chat"),
    ("باقة موبايل", "Product inquiry", "كيف أغيّر الباقة",
     "العميل يريد الانتقال إلى باقة أخرى أنسب لاستهلاكه.",
     "ادخل على التطبيق ثم الباقات واختر الباقة المناسبة واضغط تغيير الباقة. يبدأ التغيير غالبًا مع بداية دورة الفاتورة القادمة، "
     "ويمكنك مراجعة تفاصيل الباقة الجديدة قبل التأكيد.",
     "Low", "Chat"),
    ("باقة موبايل", "Technical issue", "لا توجد شبكة أو إشارة ضعيفة",
     "الموبايل لا يلتقط شبكة أو الإشارة ضعيفة ومتقطعة.",
     "فعّل وضع الطيران 10 ثوانٍ ثم أطفئه، وأعد تشغيل الهاتف، وتأكد من إدخال شريحة الخط جيدًا. جرّب الشريحة في هاتف آخر للتأكد، "
     "وإن استمرت المشكلة فقد يتطلب الأمر استبدال الشريحة من أقرب فرع.",
     "High", "Phone"),
    ("باقة موبايل", "Technical issue", "الإنترنت على الموبايل لا يعمل",
     "باقة الإنترنت فعّالة لكن التصفح لا يعمل على الهاتف.",
     "تأكد من تفعيل بيانات الهاتف وأن لديك باقة سارية ورصيدًا كافيًا، ثم تحقق من إعدادات APN وأعد ضبط إعدادات الشبكة. "
     "أعد تشغيل الهاتف وجرب مرة أخرى.",
     "Medium", "Chat"),
    ("إنترنت منزلي", "Cancellation request", "أريد إلغاء الاشتراك",
     "العميل يرغب في إلغاء خدمة الإنترنت المنزلي.",
     "لإلغاء الخدمة يلزم تقديم طلب إلغاء رسمي من التطبيق أو أقرب فرع بعد سداد المستحقات المتبقية وإعادة جهاز الراوتر المؤجَّر إن وُجد. "
     "يتم إيقاف الخدمة بنهاية دورة الفاتورة الحالية.",
     "Medium", "Phone"),
    ("إنترنت منزلي", "Refund request", "استرداد مبلغ دُفع بالخطأ",
     "العميل دفع الفاتورة مرتين أو دفع مبلغًا زائدًا ويريد استرداده.",
     "يتم احتساب المبلغ الزائد رصيدًا دائنًا يُخصم من الفاتورة التالية تلقائيًا، أو يمكن طلب رده لوسيلة الدفع الأصلية من التطبيق "
     "مع إرفاق إيصال الدفع، وعادةً يستغرق الاسترداد من 5 إلى 10 أيام عمل.",
     "Medium", "Email"),
    ("راوتر", "Technical issue", "الراوتر يعيد التشغيل كثيرًا",
     "الراوتر يفصل ويعيد التشغيل من تلقاء نفسه بشكل متكرر.",
     "تأكد من سلامة محوّل الكهرباء ووصلته، وضعه في مكان جيد التهوية بعيدًا عن الحرارة. جرّب مقبسًا آخر، وإن استمر الفصل "
     "فسجّل المشكلة لاستبدال الجهاز.",
     "High", "Phone"),
    ("Home Internet", "Technical issue", "Slow internet speed",
     "Customer reports that the home internet is much slower than the subscribed plan.",
     "Restart the router by unplugging it for 30 seconds, test the speed with a cable connected directly to the router, "
     "and move closer to the router if you use Wi-Fi. If the speed is still low after 10 minutes, report your line number so it can be checked.",
     "Medium", "Phone"),
]


def seed_personas(db: Session) -> None:
    if db.query(Persona).count():
        return
    for order, p in enumerate(PERSONAS):
        db.add(Persona(name=p["name"], role=p["role"], description=p["description"],
                       tone_instructions_ar=p["tone"], verbosity=p["verbosity"], max_words=p["max_words"],
                       is_default=p["is_default"], sort_order=order))
    db.commit()
    logger.info("Seeded %d personas", len(PERSONAS))


def seed_kb(db: Session) -> None:
    if not settings.SEED_SAMPLE_KB or db.query(KBArticle).count():
        return
    for product, ticket_type, subject, description, resolution, priority, channel in SAMPLE_KB:
        db.add(KBArticle(product=product, ticket_type=ticket_type, subject=subject, description=description,
                         resolution=resolution, status="Closed", priority=priority, channel=channel))
    db.commit()
    logger.info("Seeded %d sample knowledge-base articles", len(SAMPLE_KB))


def seed_superadmin(db: Session) -> None:
    if db.query(StaffUser).filter(StaffUser.role == "superadmin").first():
        return
    password = settings.SUPERADMIN_PASSWORD
    generated = not password
    if generated:
        password = secrets.token_urlsafe(9)
    db.add(StaffUser(username=settings.SUPERADMIN_USERNAME, password_hash=hash_password(password), role="superadmin"))
    db.commit()
    if generated:
        banner = "=" * 62
        print(f"\n{banner}\n  First run: superadmin account created\n"
              f"  username: {settings.SUPERADMIN_USERNAME}\n  password: {password}\n"
              f"  (shown once - set SUPERADMIN_PASSWORD in .env to choose your own)\n{banner}\n", flush=True)
    else:
        logger.info("Created superadmin '%s' from SUPERADMIN_PASSWORD", settings.SUPERADMIN_USERNAME)


def seed_all(db: Session) -> None:
    seed_personas(db)
    seed_kb(db)
    seed_superadmin(db)
