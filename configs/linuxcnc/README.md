# Configuración de simulación LinuxCNC (B+C head-head)

Máquina simulada con **cabezal B + C** para probar el 3+2 de IndexedCAM sin
tocar hierro. Usa la cinemática `5axiskins` de LinuxCNC (*"kinematics for XYZBC
5 axis bridge mill"*) y los planos de trabajo inclinados `G68.2`: el programa
escribe la **punta de la herramienta** y el controlador compensa el pivote.

Probada con **LinuxCNC 2.10.0~pre2**.

## Arrancar

```bash
linuxcnc configs/linuxcnc/indexedcam.ini
```

Abre la GUI **Axis** y, en otra ventana, el modelo 3D del cabezal (vismach).
Se carga solo `validate_bc.ngc`: pulsa **Cycle Start** (o F9) para verlo.

Máquina arriba la primera vez: **Enable** (reset de emergencia), **Machine On**
y **Home All**.

## Qué contiene

| Fichero | Para qué |
| --- | --- |
| `indexedcam.ini` | 6 joints `XYZBCW`, `B` = joint 3, `C` = joint 4, límites y GUI |
| `indexedcam.hal` | pivote y longitud de herramienta de `5axiskins` |
| `indexedcam_vismach.hal` | ventana 3D del cabezal (se puede quitar del INI) |
| `indexedcam.nml` | canales NML propios (números y puerto distintos de los del sistema) |
| `indexedcam.tbl` | herramientas T1 (Ø6) y T2 (Ø10), ambas con `Z0` |
| `validate_bc.ngc` | programa de validación con cuatro orientaciones |
| `validate_tools.ngc` | cambio de herramienta (T1 → T2) entre dos orientaciones |
| `posted_example.ngc` | programa real generado con **Postprocesar** (2 orientaciones, 1 herramienta) |

`indexedcam.var`, `indexedcam.var.bak`, `indexedcam_cmds.hal` e
`indexedcam_run.ini` los genera LinuxCNC al arrancar, no se versionan.

**Solo puede haber una instancia de LinuxCNC con realtime** en la máquina. Si
abres esta configuración teniendo otra sesión de LinuxCNC abierta, el arranque
falla (no es un problema de esta config: `loadrt` no puede compartir el
realtime). Los canales NML son propios para no pisar los del sistema, pero el
realtime es único.

## Cómo se comprueba la orientación

`validate_bc.ngc` recorre cuatro orientaciones con el mismo patrón que genera el
postprocesador: retirada → `G69` → indexado `B`/`C` → `G68.2 P3` (origen y +X,
luego la normal) → aproximación → trayectoria.

| # | Orientación | Bloque del plano |
| --- | --- | --- |
| 1 | cara superior | `X30 Y20 Z30 I1 J0 K0` / `I0 J0 K1` |
| 2 | cara +X | `X60 Y20 Z15 I0 J0 K-1` / `I1 J0 K0` |
| 3 | cara +Y | `X30 Y40 Z15 I0 J0 K-1` / `I0 J1 K0` |
| 4 | compuesta 45°/45° | `X60 Y40 Z30 I0.5 J0.5 K-0.7071068` / `I0.5 J0.5 K0.7071068` |

Al pasar por cada bloque, en la ventana vismach la herramienta debe quedar
**perpendicular a la cara**, y el movimiento debe ser continuo (sin cabeceos ni
saltos). En la GUI de Axis, cambiando el DRO a **modo joint**, los valores
coinciden con estos (pivote de 250 mm, herramienta de longitud 0):

| Orientación | X (joint 0) | Y (joint 1) | Z (joint 2) | B (joint 3) | C (joint 4) |
| --- | --- | --- | --- | --- | --- |
| cara superior | 30 | 20 | 30 | 0 | 0 |
| cara +X | −190 | 20 | −235 | 90 | 0 |
| cara +Y | 30 | −210 | −235 | 90 | 90 |
| compuesta 45/45 | −65 | −85 | −43,223 | 45 | 45 |

La cuenta es la de siempre: `punta = pivote + (pivote + herramienta) · eje`, con
`eje = (sinB·cosC, sinB·sinC, cosB)` y el pivote 250 mm por detrás de la punta.
Que la punta caiga en el origen del plano es lo que demuestra que el plano
`G68.2` y la cinemática del cabezal se componen bien.

## Pivote y herramienta

- **Pivote** (`5axiskins.pivot-length`, 250 mm): distancia de la punta al eje B
  **sin** herramienta. Si lo cambias, cambia también `pivot_len=` de
  `indexedcam_vismach.hal` para que el dibujo coincida.
- **Herramienta** (`5axiskins.tool-length`): está conectada a
  `motion.tooloffset.z`, así que sale de la tabla (`Z` de cada herramienta). Con
  `Z0` (lo que trae la config) el cero de Z se toma con la herramienta montada.
  Con `Z` distinto de 0, LinuxCNC suma el offset al eje Z y el módulo lo añade
  al radio del pivote; comprobado en la simulación: T2 con `Z40` en la cara +X
  deja los joints en X=−230, Z=−235 (en vez de −190/−235) con la punta en el
  mismo punto.

## Probar un programa generado por IndexedCAM

1. En FreeCAD: **IndexedCAM → Postprocesar** y guarda el `.ngc`.
2. En LinuxCNC: **File → Open** y elige ese fichero (o `axis-remote <fichero>`).
3. Cycle Start. Si el programa pide `B` fuera de `-120..120`, la máquina se
   queja por límites: ajusta `[AXIS_B]`/`[JOINT_3]` o cambia la orientación.

## Límites de recorrido

`X/Y ±500`, `Z −500..250`, `B ±120`, `C ±360`, `W −100..500`. No son los de una
máquina real, pero **tienen que cubrir el pivote**:

- Con **B = 0** el carro queda a la altura de la punta, así que el recorrido
  **Z+ debe cubrir la altura de retirada**. Un programa que retire a 130 mm por
  encima de una pieza que está a Z=30 pide `joint 2 = 130`; por eso `Z MAX_LIMIT`
  es 250 y no 100. Si lo bajas, verás
  `Linear move on line N would exceed Z's positive limit`.
- Con **B = 90** el carro baja `pivote` mm respecto a la punta, así que `Z−`
  tiene que llegar a `−pivote` como mínimo.

Las retiradas que genera IndexedCAM son la esfera de seguridad, medida **desde
la pieza**: su radio es la media diagonal de la pieza. En una pieza de 60×40×30
(39,05 mm de media diagonal) eso son 24 mm sobre la cara superior y 9 mm sobre
una lateral con el ajuste por defecto. En una máquina real comprueba que caben
en su `Z+`.

La altura se controla con **IndexedCAM → Seguridad** en FreeCAD, que guarda el
margen en el Job: **0 mm por defecto** (el mínimo geométrico) y lo que haga
falta si el Preview detecta colisión en los giros. El valor lo usan por igual el
Preview y el postprocesador.

## Comprobación automática

```bash
python3 tests/linuxcnc/check_sim.py
cat /tmp/indexedcam_sim.log
```

Arranca esta config en un display virtual (`Xvfb`), referencia (home) la
máquina, manda los cuatro planos por MDI y compara los joints con la tabla de
arriba. Termina en `PASS`. No toca ninguna máquina real.

Para lanzar además programas completos (por ejemplo uno generado con
**Postprocesar**) y comprobar que se ejecutan enteros, **sin errores del
controlador** (límites, avances, comentarios anidados) y moviendo la máquina:

```bash
python3 tests/linuxcnc/check_sim.py \
    configs/linuxcnc/validate_bc.ngc \
    configs/linuxcnc/validate_tools.ngc \
    configs/linuxcnc/posted_example.ngc
```

Los errores se leen del **canal de errores NML** del intérprete
(`tests/linuxcnc/error_watch.py`), no solo del log: un `G1` sin avance, un
límite de recorrido o un comentario anidado acaban ahí y el log no siempre los
muestra. Cada programa se ejecuta en su propia instancia, porque AXIS no cambia
de fichero con el intérprete cargado y arrastraría el estado modal del anterior.

Los tests rápidos (`python3 -m pytest tests/test_linuxcnc_config.py`) validan el
INI, el HAL, que cada plano de `validate_bc.ngc` sea exactamente el `LocalFrame`
que IndexedCAM calcula para esos ángulos B/C, y —sin necesidad de arrancar
LinuxCNC— que **todos los movimientos** de los dos programas quepan en los
límites del INI, calculando el carro con la misma cinemática que `5axiskins`
(valores contrastados con la máquina real).

`check_sim.py` sale con código 2 y un aviso si detecta el realtime ocupado por
otra sesión de LinuxCNC.
