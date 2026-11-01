# Cinemática de máquina

## Máquina objetivo

- **Tipo:** cabezal B + C (B+C Head).
- **Eje B:** inclinación del cabezal.
- **Eje C:** rotación alrededor del eje Z.
- **Objetivo de orientación:** alinear el eje Z local de la herramienta con la normal de la cara.

## Modo de operación

**Soportado inicialmente:** mecanizado 3+2 indexado. B y C se posicionan para orientar la herramienta y permanecen fijos durante el corte; los ejes lineales pueden moverse.

**No soportado inicialmente:** mecanizado simultáneo de 5 ejes o movimiento de B/C durante el corte.

La conversión de la normal de la cara a posiciones B/C debe respetar los sentidos de giro, ceros, límites y convenciones del controlador de la máquina. La orientación calculada debe validarse con la configuración real del cabezal.

## Implementación (`IndexedCAM/Machine/bc_head.py`)

Convención: `R = Rz(C) @ Ry(B)`, `n = (sin B cos C, sin B sin C, cos B)`. Inversa: `B = acos(nz)`, `C = atan2(ny, nx)`.

- `normal_to_bc(normal, previous_c=None)` → `BCAngles(b, c)` en grados, B∈[0,180], C∈[−180,180).
- Singularidad (normal ∥ Z): C indeterminado; se conserva `previous_c` o se usa 0. Z invertida también es singular.
- `bc_to_normal(b, c)` y `verify_solution(...)` reconstruyen y validan la normal.
- Vectores nulos, no finitos o de longitud ≠ 3 lanzan `ValueError`.
- Casos de aceptación: cara superior → B=0 C=0; cara X → B=90 C=0; cara Y → B=90 C=90.

Tests: `python -m pytest tests`.
