"""Small untrusted UI hints, never catalog evidence or executable instructions.

Allowlist reviewed from storefront commit25aa9ce22a0652375f0554576b88f24f83b65b88:
src/app routes and src/products/index.ts. Post-purchase and offer routes are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

PublicPath = Literal[
    '/',
    '/grafismo-fonetico',
    '/grafismo-fonetico/',
    '/soporte',
    '/soporte/',
    '/arrepentimiento',
    '/arrepentimiento/',
    '/aviso-legal',
    '/aviso-legal/',
    '/compras-y-reembolsos',
    '/compras-y-reembolsos/',
    '/cookies',
    '/cookies/',
    '/privacidad',
    '/privacidad/',
    '/terminos',
    '/terminos/',
]
Presentation = Literal['compact', 'expanded', 'page']
PUBLIC_PATHS = frozenset(get_args(PublicPath))
PRESENTATIONS = frozenset(get_args(Presentation))


@dataclass(frozen=True, slots=True)
class VisitorContext:
    opened_path: str | None = None
    current_path: str | None = None
    presentation: str | None = None

    def __post_init__(self) -> None:
        if any(
            path is not None and path not in PUBLIC_PATHS for path in (self.opened_path, self.current_path)
        ):
            raise ValueError('visitor path must be an allowlisted public route')
        if self.presentation is not None and self.presentation not in PRESENTATIONS:
            raise ValueError('visitor presentation must be an allowed hint')

    def payload(self) -> dict[str, str | None]:
        def canonical(path: str | None) -> str | None:
            return f'{path.rstrip("/")}/' if path else None

        return {
            'opened_path': canonical(self.opened_path),
            'current_path': canonical(self.current_path),
            'presentation': self.presentation,
        }

    @property
    def empty(self) -> bool:
        return not any((self.opened_path, self.current_path, self.presentation))
