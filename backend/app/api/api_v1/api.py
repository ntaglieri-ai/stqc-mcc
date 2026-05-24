from fastapi import APIRouter, Depends

from backend.app.api.api_v1.endpoints import certificates, commessa, distinta, inventario, qr, stock, warehouse
from backend.app.core.auth import require_auth

api_router = APIRouter(dependencies=[Depends(require_auth)])
api_router.include_router(warehouse.router, prefix="/warehouse", tags=["warehouse"])
api_router.include_router(distinta.router, prefix="/warehouse/distinta", tags=["distinta"])
api_router.include_router(commessa.router, prefix="/commesse", tags=["commesse"])
api_router.include_router(qr.router, prefix="/qr", tags=["qr"])
api_router.include_router(inventario.router, prefix="/inventario", tags=["inventario"])
api_router.include_router(certificates.router, prefix="/warehouse/receipts", tags=["certificates"])
api_router.include_router(stock.router, prefix="/stock", tags=["stock"])
