# Postprocesador LinuxCNC

Genera el G-code de un Job indexado para una máquina de **cabezal B + C** con
LinuxCNC. El programa corre bajo un **plano de trabajo inclinado** (`G68.2`) y
la compensación del pivote la hace el módulo de cinemática **`5axiskins`**: el
programa escribe la **punta de la herramienta** y el controlador calcula los
ejes lineales.

## Qué emite

Por cada orientación del programa:

1. Retirada en el eje de la herramienta hasta `safe_z` (fuera de la esfera de
   seguridad, plano actual).
2. `G69` — anula el plano anterior.
3. `M5` y `M9` — husillo y refrigerante fuera (configurable).
4. Si cambia la herramienta: `G49`, `M6 T…` y `G43.4 H…`.
5. `G54` (el WCS del Setup) y `G0 B… C…` — indexado.
6. `G68.2 P3 Q1 …` (origen y +X del plano) y `G68.2 P3 Q2 …` (normal +Z).
7. `G0 Z<clearance>` — aproximación dentro del plano.
8. Las operaciones **tal cual**: los movimientos de `Path.Commands` se emiten
   sin transformar, en coordenadas locales de la cara.

Ejemplo real (Job con dos orientaciones y una herramienta):

```gcode
%
(IndexedCAM - Test000)
(Herramientas: T1 Endmill D5)
G21 G90 G17 G94 G40 G80
G69 (cancela cualquier plano previo)
G49
M6 T1 (cambio de herramienta T1 Endmill D5)
G43.4 H1 (longitud de herramienta)
G54 (sistema de coordenadas)
G0 B90.000 C0.000 (indexado)
G68.2 P3 Q1 X70.000 Y40.000 Z45.000 I0.000 J0.000 K-1.000 (plano: origen y +X)
G68.2 P3 Q2 I1.000 J0.000 K0.000 (plano: normal +Z)
G0 Z10.000 (aproximacion en el plano)
(Operacion Contour - T1 Endmill D5)
S10000 M3 (husillo horario)
M8 (refrigerante ON)
G0 X12.500 Y17.500
G1 X12.500 Y17.500 Z5.000
(...)
G0 Z109.051 (retirada libre para indexar)
G69 (anula el plano inclinado)
M5 (para el husillo)
M9 (refrigerante OFF)
G54 (sistema de coordenadas)
G0 B0.000 C0.000 (indexado)
G68.2 P3 Q1 X40.000 Y40.000 Z60.000 I1.000 J0.000 K0.000 (plano: origen y +X)
G68.2 P3 Q2 I0.000 J0.000 K1.000 (plano: normal +Z)
(...)
M30 (fin de programa)
%
```

El bloque `G68.2 P3` usa dos vectores en lugar de ángulos de Euler: el primero
da el **origen** del plano y su **+X**, el segundo su **+Z** (la normal). Así el
plano es exactamente el `LocalFrame` del Setup, sin singularidades ni
ambigüedades de Euler. LinuxCNC deriva el +Y como `+Z × +X`, que es como se
construye nuestro marco, y lo comprueba `tests/freecad/check_post.py`.

## Configuración del controlador

`5axiskins` (`src/emc/kinematics/5axiskins.c`, *"kinematics for XYZBC 5 axis
bridge mill"*) es la cinemática de un cabezal B+C: el eje Z del programa es la
**punta** de la herramienta y el módulo coloca los ejes lineales a partir del
pivote. Está en LinuxCNC desde 2.9; la configuración de referencia del propio
proyecto es `configs/sim/axis/vismach/5axis/bridgemill/5axis.ini`.

El repositorio incluye una configuración de simulación ya probada,
[configs/linuxcnc](../configs/linuxcnc/README.md), que sirve de plantilla para
la máquina real. Lo esencial:

```ini
[TRAJ]
COORDINATES = XYZBCW
ANGULAR_UNITS = degree

[KINS]
JOINTS = 6                      ; x:0 y:1 z:2 b:3 c:4 w:5
KINEMATICS = 5axiskins coordinates=xyzbcw
```

```hal
# pivote mecanico (punta -> eje B) SIN la herramienta, y longitud de la
# herramienta en uso (sale de la tabla con G43/G43.4)
setp 5axiskins.pivot-length 250
net tool-len motion.tooloffset.z => 5axiskins.tool-length
```

Comprobado en LinuxCNC 2.10.0~pre2 midiendo los joints: con pivote 250 y
herramienta de longitud 0, el origen de la cara +X (`G68.2` con normal +X y
`G0 X0 Y0 Z0`) deja `X=-190, Z=-235`; la cara compuesta 45°/45° deja
`X=-65, Y=-85, Z=-43,223`. Y con una herramienta de 40 mm en la tabla, la misma
cara +X pasa a `X=-230` con la punta en el mismo punto: el offset de Z entra en
el eje Z y el módulo lo añade al radio del pivote. Eso es lo que hacen los dos
pines de arriba.

`5axiskins` es un módulo de cinemáticas conmutables con tres tipos: 0 =
`5axiskins`, 1 = identidad, 2 = `userkins`; por defecto arranca en el 0. Los
nombres de los pines se comprueban con `halcmd show pin | grep 5axiskins` antes
de mecanizar nada.

### G43 y G43.4

- `5axiskins` declara su cinemática como **primaria** (`.primary = 1`).
- Con `KINEMATICS = 5axiskins` (sin `identityfirst`) la máquina arranca ya en
  esa cinemática: `G43` basta.
- Con una configuración de cinemáticas conmutables (`identityfirst`), hace
  falta `G43.4` para activarla; `G49` vuelve a identidad.
- Por eso el post usa **`G43.4` por defecto** (`LinuxCNCConfig.tool_length`), que
  funciona en ambos casos. Con `tool_length="G43"` se emite `G43` y con
  `tool_length="none"` no se emite ninguna compensación (la gestión queda en
  manos del operador).

## Modelo cinemático y sentidos

Coincide exactamente con lo que ya calcula IndexedCAM:

| | IndexedCAM | LinuxCNC `5axiskins` |
| --- | --- | --- |
| Eje de herramienta | `n = (sinB·cosC, sinB·sinC, cosB)` | `p − t = (sinB·cosC, sinB·sinC, −cosB)` |
| Pivote | `punta + pivot_distance · n` | `punta + (pivot + tool + W) · n` |
| Relación | `pivot_distance` = pivote + herramienta | misma |

`5axiskins` usa `180° − B`, así que **el sentido del tilt es el opuesto al
convencional** (giro a derechas alrededor de +Y), como avisa su nota 10. Además
cada cabezal tiene su cero. Por eso el post aplica un mapeo configurable:

```python
AxisSigns(b_sign=1.0, c_sign=1.0, b_zero=0.0, c_zero=0.0)   # por defecto
# palabra = sign · (ángulo − cero)
```

Por defecto se cumple: **B+ inclina la herramienta hacia +X con C=0** y **C+
gira en sentido antihorario visto desde +Z**. Si tu cabezal es al revés, usa
`AxisSigns(b_sign=-1)` (o `c_sign`, `b_zero`, `c_zero`) sin tocar la geometría.

## Alturas

- `safe_z`: Z local por encima de la **esfera de seguridad** (`SafetySphere`);
  ahí se indexa. Es el mismo número que usa el Preview, así que la retirada del
  G-code coincide con lo que se ve.
- `clearance_z`: primera Z del primer movimiento de la orientación (donde CAM
  manda la herramienta), siempre que esté entre la cara (Z local 0) y `safe_z`.
  Si el camino empieza por debajo de la cara, la aproximación se queda en
  `safe_z` y es el propio camino el que baja.

Ambas están en coordenadas locales del plano, así que la retirada es siempre
**paralela al eje de la herramienta**.

`safe_z` se mide **desde la pieza**, así que un programa puede pedir más
recorrido del que tiene la máquina en Z+. Con B=0 el carro está justo en la
altura de la punta: una retirada a 114 mm sobre una cara que está a Z=60 exige
`Z+ ≥ 174`. Antes de mecanizar comprueba que la altura de retirada cabe en tu
`[AXIS_Z]MAX_LIMIT`.

### Distancia de seguridad (configurable)

El radio de esa esfera es *media diagonal de la pieza + herramienta +
portaherramientas* **+ el margen de seguridad**, que se configura en FreeCAD con
**IndexedCAM → Seguridad** y se guarda en el Job (viaja en el `.FCStd`). Por
defecto es **0 mm**, es decir la retirada **mínima** que todavía gira el cabezal
con el portaherramientas fuera de la pieza. Súbelo si el Preview marca colisión
en los giros.

El mismo número lo usan el Preview y el postprocesador, así que el G-code retira
exactamente lo que se ve. Implementación: `Core/safety.py` (`SafetyConfig`,
`JobSafetyStorage`) y `Commands/safety.py`.

## Avances (F)

CAM escribe en el `F` de cada operación el `VertFeed`/`HorizFeed` del
`ToolController`, y un controlador recién creado los tiene **a cero**: entonces
CAM emite `G0 F0` y una `G1` sin `F`, y LinuxCNC se niega con *"No se puede
hacer G1 con velocidad de avance cero"*.

El post no deja pasar nunca ese caso. Antes de los movimientos de una operación
sin avance propio emite uno, con este orden de preferencia:

1. el `F` que traigan los movimientos de CAM,
2. el avance del `ToolController` de esa operación (`HorizFeed`, si no está,
   `VertFeed`),
3. `LinuxCNCConfig.default_feed` (300 mm/min por defecto).

El bloque va comentado (`avance: CAM no lo trae en esta operacion`) para que se
vea en el G-code. Además, si un movimiento de corte llegara sin `F` con el
avance modal a cero, se le inyecta el avance por defecto. Lo correcto sigue
siendo rellenar los avances en el `ToolController`: así el G-code lleva los
tuyos.

## Arcos

Bajo `G68.2` los bloques se programan en el plano de la cara (X e Y en el
plano, Z según la normal), así que **todos los arcos son válidos como G2/G3** y
no se linealiza nada: cada cara tiene su propio plano. Los centros `I`/`J` se
emiten tal como los da CAM (incrementales respecto al inicio, que es lo que
LinuxCNC espera por defecto con `G91.1`).

## Uso

- **GUI**: **IndexedCAM → Postprocesar**, con el Job o una operación
  seleccionada. Pide el fichero `.ngc` y escribe el programa con los valores
  por defecto (`G54`, mm, 3 decimales, `G43.4`, sin números de línea).
  Muestra un resumen: orientaciones, operaciones, herramientas y líneas.
- **Consola**:

```python
import FreeCAD, FreeCADGui
from IndexedCAM.Commands.context import build_context, selected_objects
from IndexedCAM.Commands.post import build_post, write_program
from IndexedCAM.Post.linuxcnc import AxisSigns, LinuxCNCConfig, LinuxCNCPost

doc = FreeCAD.ActiveDocument
ctx = build_context(doc, None)          # el único Job del documento
post = build_post(doc, ctx.manager, ctx.program, ctx.bridge, ctx.job.Label)
config = LinuxCNCConfig(signs=AxisSigns(b_sign=-1.0), line_numbers=True)
text = LinuxCNCPost().render(post, config)
write_program(text, "/tmp/prueba.ngc")
```

## Validación en vacío (antes de cortar)

1. `halcmd show pin | grep 5axiskins` — confirma los pines de pivote.
2. Con la máquina en el aire, ejecuta el programa con el **offset de pieza
   alto** (por ejemplo `G54 Z+100`) y observa: la herramienta debe inclinarse y
   apuntar perpendicular a cada cara; la punta debe describir la trayectoria
   prevista, sin cabeceos ni saltos.
3. Comprueba la retirada: siempre paralela al eje de la herramienta y antes de
   cualquier giro.
4. Si la inclinación va al lado contrario, corrige `AxisSigns`.
5. Revisa `tests/freecad/check_post.py`: verifica, leyendo el G-code generado,
   que el plano reconstruido por el controlador coincide con el marco del
   Setup y que cada movimiento se emite sin transformar.

## Limitaciones

- Un solo WCS por orientación (`IndexedSetup.wcs`, por defecto `G54`); no se
  emiten offsets medidos.
- No se emite `G12.1`/`G13.1`: se apoya en `5axiskins` + `G43.4`.
- El pivote no se modela con desplazamiento lateral respecto al eje C.
- Operación vacía = paso omitido, pero la orientación sigue apareciendo si
  tiene alguna operación con movimientos.
- Los comentarios del G-code se escriben en ASCII (sin acentos ni `Ø`).
- El post no comprueba colisiones: eso es el Preview.

Implementación: `Core/post_program.py` (modelo), `Core/post_builder.py`
(construcción), `Post/linuxcnc.py` (formato) y `Commands/post.py` (comando).
