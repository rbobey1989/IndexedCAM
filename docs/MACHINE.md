 # Definición de máquina

## Tipo

Cabezal B + C.

## Ejes

| Eje | Rango |
| --- | --- |
| B | 0° a +180° |
| C | −360° a +360° |

## Vector de herramienta

La orientación del vector de herramienta se define mediante los ángulos B y C.

## Objetivo

Alinear el eje Z de la herramienta con la normal de la cara seleccionada.

## Implementación (`IndexedCAM/Machine/bc_machine.py`)

- `AxisLimits(minimum, maximum)`: intervalo cerrado en grados; rechaza valores no finitos o invertidos.
- `BCMachine(b_limits=(0, 180), c_limits=(-360, 360))`:
  - `is_reachable(b, c)` / `validate(b, c)`: comprueban límites (`validate` lanza `ValueError` indicando el eje).
  - `tool_vector(b, c)`: dirección unitaria del eje de herramienta, `(sin B cos C, sin B sin C, cos B)`.
  - `rotation_matrix(b, c)`: `Rz(C) @ Ry(B)`; su tercera columna es el vector de herramienta.
- Convención de signos y ceros igual a `MACHINE_KINEMATICS.md`; debe ajustarse a la máquina real.
- La elección de la solución B/C alcanzable para una normal (p. ej. `nz < 0`) corresponde a `OrientationSolver` (#3).

## Envolvente de herramienta y cabezal (#15)

`BCMachine.envelope` (`Machine/envelope.py`) modela la herramienta, el portaherramientas y el cabezal como cilindros coaxiales apilados a lo largo del eje de la herramienta, medidos desde la punta (mm), más `pivot_distance` (punta → pivote de B). Valores por defecto: herramienta Ø10×40, portaherramientas R20×50, cabezal R60×150, pivote a 120 mm; **son genéricos y deben ajustarse a la máquina real**.

- `Envelope.place(punta, B, C)` devuelve los cilindros (eje inicio→fin) en coordenadas de pieza; `pivot(...)` la posición del pivote.
- `Envelope.with_tool(radio, largo)` sustituye la herramienta; `CamBridge.envelope_for(operación, base)` la toma del controlador de herramienta de CAM (Diameter/2 y Length).
- `to_dict`/`from_dict` para guardar la definición. Lo usarán el planificador de transiciones (#16) y el comprobador de colisiones (#17).
