# api.py – تجميع جميع الـ routers في نقطة واحدة (APIRouter رئيسية)
"""Central API router aggregating all project endpoints into a unified interface, preserving route prefixes and tags while simplifying FastAPI integration, maintainability, and endpoint management."""


from fastapi import APIRouter

# استيراد جميع الـ routers (كل ملف router يعرف متغيّر "router")
from app.routers import (
    admin,
    auth,
    documents,
    pages,
    portal,
    staff,
    vonage,
    files,  # router للملفات التي أضفناها حديثاً
)

# كائن APIRouter رئيسي يجمع الكل
api_router = APIRouter()

# تضمين كل router مع الحفاظ على الـ prefix والـ tags المعرفة داخله
# (لا نضيف prefix إضافي هنا لأن كل router يملك prefix خاص به)
api_router.include_router(admin.router)
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(pages.router)
api_router.include_router(portal.router)
api_router.include_router(staff.router)
api_router.include_router(vonage.router)
api_router.include_router(files.router)

# إذا رغبت في إضافة مسار يوضح جميع endpoints المتاحة (للتطوير فقط)
@api_router.get("/endpoints", tags=["Utility"])
async def list_endpoints():
    """تعيد قائمة بسيطة بأسماء الـ routers وتفاصيل الـ prefix.
    يستخدم في بيئة التطوير لتفقد ما تم تسجيله.
    """
    return {
        "admin": admin.router.prefix,
        "auth": auth.router.prefix,
        "documents": documents.router.prefix,
        "pages": pages.router.prefix,
        "portal": portal.router.prefix,
        "staff": staff.router.prefix,
        "vonage": vonage.router.prefix,
        "files": files.router.prefix,
    }
