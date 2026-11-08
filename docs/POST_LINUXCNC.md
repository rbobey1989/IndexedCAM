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

El radio de esa esfera es la **media diagonal de la pieza + el margen de
seguridad**. **No** se suma la longitud de la herramienta ni la del
portaherramientas: en el giro la punta se desliza sobre la esfera con la
herramienta apuntando **radialmente hacia fuera**, así que el vastago, el
portaherramientas y el cabezal están siempre *más lejos* del centro que la
punta. Media diagonal es, por tanto, el radio mínimo que mantiene toda la
envolvente fuera de la pieza (lo comprueba
`tests/test_transition_planner.py::test_nothing_in_the_envelope_comes_closer_than_the_radius`
y, con `Part`, `tests/freecad/check_collision.py`).

El margen se configura en FreeCAD con **IndexedCAM → Seguridad**, se guarda en
el Job (viaja en el `.FCStd`) y por defecto es **0 mm**. El mismo número lo usan
el Preview y el postprocesador, así que el G-code retira exactamente lo que se
ve. Implementación: `Core/safety.py` (`SafetyConfig`, `JobSafetyStorage`) y
`Commands/safety.py`.

Para una pieza de 60×40×30 la media diagonal son 39,05 mm, así que la retirada
queda **24 mm sobre la cara superior** y **9 mm sobre una cara lateral**. Antes
de esta corrección eran 124 y 109 mm: se sumaban 100 mm de herramienta y
portaherramientas que no hacen falta.

**Cuándo subir el margen**: al indexar, el control mantiene la punta y gira el
cabezal, y en esa maniobra el portaherramientas (radio 20 mm en la configuración
de simulación) pasa a la altura de la punta. Con una retirada muy corta y una
pieza ancha, el portaherramientas puede barrer material que esté por debajo.
Si el Preview marca colisión en un giro, o si tu portaherramientas es ancho y la
pieza grande, sube el margen hasta que desaparezca.

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

## Cabezal vertical antes de tocar la longitud de herramienta

El post pone siempre el cabezal vertical (`G0 B… C…` con los ceros configurados)
**antes** de `G49`/`G43.4`, al cambiar de herramienta y al terminar el programa.
No es un adorno: es obligatorio.

`G49` y `G43.4` conmutan el **tipo de cinemática** del módulo (primaria ↔
identidad), y al hacerlo el controlador convierte la posición actual entre el
marco de la máquina y el del mundo. Con el cabezal **inclinado** esa conversión
reescribe las coordenadas de programa con los valores de las juntas (cientos de
mm), y el siguiente movimiento de `B`/`C` se planifica desde esos números, así
que puede salirse del recorrido. Los dos síntomas típicos, ambos observados:

- al terminar el mecanizado la herramienta "aparece" en unas coordenadas
  lejanas que no salen de ninguna parte (el DRO, no la máquina);
- al volver a pulsar play, `Linear move on line 14 would exceed Z's positive
  limit` en el primer indexado.

Con `B = C = 0` los dos marcos coinciden, así que la conmutación no cambia
ningún número. De ahí la regla. `tests/linuxcnc/check_sim.py` ejecuta **cada
programa dos veces seguidas** en la misma sesión y exige que las dos pasadas
terminen sin errores.

## Arcos

Bajo `G68.2` los bloques se programan en el plano de la cara (X e Y en el
plano, Z según la normal), así que **todos los arcos son válidos como G2/G3** y
no se linealiza nada: cada cara tiene su propio plano. Los centros `I`/`J` se
emiten tal como los da CAM (incrementales respecto al inicio, que es lo que
LinuxCNC espera por defecto con `G91.1`).

## Uso

- **GUI**: **IndexedCAM → Postprocesar**, con el Job o una operación
  seleccionada. Abre la **ventana de opciones** (ver abajo), luego pide el
  fichero `.ngc` y escribe el programa. Al terminar muestra un resumen:
  orientaciones, operaciones, herramientas y líneas.

## Opciones del postprocesador

Al pulsar el icono **Postprocesar** se abre una ventana con todo lo que depende
de la máquina y del controlador, no de la geometría:

| Grupo | Opción | Por defecto |
| --- | --- | --- |
| Cabezal | sentido de B (`+`/`−`), cero de B | `+`, 0° |
| Cabezal | sentido de C (`+`/`−`), cero de C | `+`, 0° |
| Control | longitud de herramienta | `G43.4` |
| Control | refrigerante (`M8`/`M7`) | sí |
| Control | parar el husillo entre orientaciones | sí |
| Formato | unidades (mm/pulgadas), decimales | mm, 3 |
| Formato | avance por defecto, numerar líneas | 300 mm/min, no |

La ventana muestra además la lista de orientaciones con su **B, C y la normal**,
que es lo que el post va a usar. Se guarda en el Job (viaja en el `.FCStd`), así
que el mismo Job se postprocesa igual la próxima vez. Implementación:
`Core/post_settings.py` (`PostSettings`, `JobPostStorage`),
`Post/linuxcnc.py` (`LinuxCNCConfig`, `AxisSigns`) y `Commands/post.py`.

### Si una cara lateral se mecaniza "desde dentro"

Síntomas: la cara superior sale bien, pero en una lateral la herramienta entra
por el interior del material. Casi siempre es el **sentido del eje B** de esa
máquina (polaridad del motor o cero distinto del que asume el post), no la
geometría:

1. Mira la normal de la orientación en la ventana de opciones. Para una cara
   `+X` debe ser `(1, 0, 0)` con `B=90, C=0`.
2. Si coincide y aun así entra por dentro, invierte **sentido de B** y vuelve a
   postprocesar: con B=0 (cara superior) el signo no influye, así que la cara
   buena sigue bien y la lateral cambia de lado.
3. Si la que está mal es la de `+Y`, prueba con el sentido de C o con los ceros.
4. El programa generado lleva en la cabecera el mapeo aplicado
   (`B gain … zero …, C gain … zero …`) y el B/C de cada orientación, así que se
   puede comprobar sin abrir la ventana.

Esto es lo mismo que valida la simulación de `configs/linuxcnc`: con
`5axiskins`, `B=90 C=0` pone la herramienta hacia `+X` y la punta queda en el
plano de la cara, que es el valor por defecto.

### Valores de referencia por cara

Con pivote 250 mm y una pieza de 60×40×30 en el origen, el programa que genera
el post (sentidos por defecto) deja estos ángulos y este eje de herramienta:

| Cara | normal | B | C | eje resultante |
| --- | --- | --- | --- | --- |
| superior | (0, 0, 1) | 0 | 0 | (0, 0, 1) |
| frontal `+X` | (1, 0, 0) | 90 | 0 | (1, 0, 0) |
| trasera `-X` | (−1, 0, 0) | 90 | 180 | (−1, 0, 0) |
| derecha `+Y` | (0, 1, 0) | 90 | 90 | (0, 1, 0) |
| izquierda `-Y` | (0, −1, 0) | 90 | −90 | (0, −1, 0) |

Se puede comprobar en la máquina sin mecanizar: en la GUI de Axis cambia el DRO
a **modo joint**, ejecuta la orientación y lee `joint 3` (B) y `joint 4` (C). El
eje de la herramienta es `(sinB·cosC, sinB·sinC, cosB)`; para la cara `+Y` debe
salir `(0, 1, 0)`, no `(1, 0, 0)`.

`tests/linuxcnc/check_sim.py` hace exactamente esa comprobación en el simulador
para las cuatro orientaciones de `validate_bc.ngc` y exige que el eje coincida
con la normal del plano.

### Si solo fallan las caras laterales en Y (frontal/posterior)

Que la herramienta se quede horizontal apuntando en la dirección de otra cara
(y que cambiar el sentido o el cero de C no haga nada) significa que **el eje C
no está inclinando el cabezal** en el control, no que el post esté mal: con una
máquina `R = Rz(C)·Ry(B)`, invertir B se compensa solo con negar B (el C no hay
que tocarlo), así que si C no cambia nada, la cinemática del control no está
aplicando el giro.

Comprueba en el control:

```bash
inivar -ini <tu>.ini -sec KINS -var KINEMATICS   # debe ser 5axiskins coordinates=xyzbcw
halcmd show pin 5axiskins                        # pivot-length y tool-length
halcmd show pin joint.4.pos-fb                   # el joint de C tiene que moverse
```

Si `KINEMATICS` es `trivkins` (identidad), el control no compone B y C: el
programa tendría que llevar ya la posición del pivote (ruta B del diseño) y el
eje de la herramienta depende solo de B, que es justo el síntoma.

### Si todo está bien salvo el dibujo de la vista previa de Axis

El visor 3D de Axis **no simula la máquina**: orienta la herramienta aplicando
las rotativas en el **orden de `[DISPLAY] GEOMETRY`** (`ToolPart._apply_rotary`
en `rs274/glcanon_scene.py`). Para que el dibujo coincida con
`R = Rz(C)·Ry(B)` la cadena tiene que llevar **C antes que B**:

```ini
[DISPLAY]
GEOMETRY = XYZCBW
```

Con `GEOMETRY = XYZBC` la C gira la herramienta sobre su propio eje y no cambia
la orientación: la herramienta se ve horizontal apuntando siempre al mismo lado
y da la impresión de que la C no funciona, aunque el cabezal sí gira (se ve en
la ventana vismach y en el DRO en modo joint). Es el valor que trae el ejemplo
de LinuxCNC del puente de 5 ejes.

`tests/test_linuxcnc_config.py` comprueba que el orden de las rotativas del INI
dibuja la herramienta normal a las caras `+X`, `+Y` y `−Y`, y que con el orden
contrario la C deja de tener efecto.
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
