 # Definición de máquina

## Tipo

Cabezal B + C.

## Ejes

| Eje | Rango |
| --- | --- |
| B | −90° a +90° |
| C | −360° a +360° |

## Vector de herramienta

La orientación del vector de herramienta se define mediante los ángulos B y C.

## Objetivo

Alinear el eje Z de la herramienta con la normal de la cara seleccionada.

## Implementación (`IndexedCAM/Machine/bc_machine.py`)

- `AxisLimits(minimum, maximum)`: intervalo cerrado en grados; rechaza valores no finitos o invertidos.
- `BCMachine(b_limits=(-90, 90), c_limits=(-360, 360))`:
  - `is_reachable(b, c)` / `validate(b, c)`: comprueban límites (`validate` lanza `ValueError` indicando el eje).
  - `tool_vector(b, c)`: dirección unitaria del eje de herramienta, `(sin B cos C, sin B sin C, cos B)`.
  - `rotation_matrix(b, c)`: `Rz(C) @ Ry(B)`; su tercera columna es el vector de herramienta.
- Convención de signos y ceros igual a `MACHINE_KINEMATICS.md`; debe ajustarse a la máquina real.
- La elección de la solución B/C alcanzable para una normal (p. ej. `nz < 0`) corresponde a `OrientationSolver` (#3).
