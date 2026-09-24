"""Registro de tenant + usuario admin, y login."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant, Usuario
from app.schemas import RegistroRequest, LoginRequest, TokenResponse, UsuarioResponse
from app.security import hash_password, verify_password, crear_token
from app.deps import get_usuario_actual

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/registro", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def registro(data: RegistroRequest, db: Session = Depends(get_db)):
    """Crea un tenant nuevo (estudio contable) con su primer usuario admin."""
    existente = db.query(Usuario).filter(Usuario.email == data.email).first()
    if existente:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese email ya esta registrado")

    tenant = Tenant(nombre=data.nombre_tenant)
    db.add(tenant)
    db.flush()  # asigna tenant.id sin cerrar la transaccion

    usuario = Usuario(
        tenant_id=tenant.id,
        email=data.email,
        password_hash=hash_password(data.password),
        rol="admin",
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)

    token = crear_token(usuario_id=usuario.id, tenant_id=tenant.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.email == data.email).first()
    if not usuario or not verify_password(data.password, usuario.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email o contrasena incorrectos")

    token = crear_token(usuario_id=usuario.id, tenant_id=usuario.tenant_id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UsuarioResponse)
def me(usuario: Usuario = Depends(get_usuario_actual)):
    return usuario
