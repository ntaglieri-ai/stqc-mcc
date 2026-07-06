from fastapi import APIRouter, Depends

from backend.app.api.api_v1.endpoints import admin, auth, certificates, commessa, distinta, inventario, officina, qr, scanner, stock, warehouse
from backend.app.core.auth import require_auth

# Public routes — no auth required
public_router = APIRouter()
public_router.include_router(auth.router, prefix="/auth", tags=["auth"])
public_router.include_router(scanner.router, prefix="/scanner", tags=["scanner"])

# Protected routes — JWT required
api_router = APIRouter(dependencies=[Depends(require_auth)])
api_router.include_router(warehouse.router, prefix="/warehouse", tags=["warehouse"])
api_router.include_router(distinta.router, prefix="/warehouse/distinta", tags=["distinta"])
api_router.include_router(commessa.router, prefix="/commesse", tags=["commesse"])
api_router.include_router(qr.router, prefix="/qr", tags=["qr"])
api_router.include_router(inventario.router, prefix="/inventario", tags=["inventario"])
api_router.include_router(certificates.router, prefix="/warehouse/receipts", tags=["certificates"])
api_router.include_router(officina.router, prefix="/officina", tags=["officina"])
api_router.include_router(stock.router, prefix="/stock", tags=["stock"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
