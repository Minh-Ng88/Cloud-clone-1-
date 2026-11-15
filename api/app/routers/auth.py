from fastapi import APIRouter, Depends

from app.errors import ApiError
from app.schemas import LoginIn, TokenOut, UserOut
from app.security import Principal, authenticate, create_token, current_principal

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn):
    p = authenticate(body.username, body.password)
    if p is None:
        raise ApiError(401, "INVALID_CREDENTIALS", "Sai tên đăng nhập hoặc mật khẩu")
    token, ttl = create_token(p)
    return TokenOut(access_token=token, expires_in=ttl, user=UserOut(user_id=p.user_id, role=p.role))


@router.get("/me", response_model=UserOut)
def me(p: Principal = Depends(current_principal)):
    return UserOut(user_id=p.user_id, role=p.role)
