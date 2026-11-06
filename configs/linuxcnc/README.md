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
| `indexedcam.tbl` | herramientas T1 (Ø6) y T2 (Ø10), ambas con `Z0` |
| `validate_bc.ngc` | programa de validación con cuatro orientaciones |
| `posted_example.ngc` | programa real generado con **Postprocesar** (2 orientaciones, 1 herramienta) |

`indexedcam.var`, `indexedcam.var.bak` e `indexedcam_cmds.hal` los genera
LinuxCNC al arrancar, no se versionan.

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

Los límites de recorrido (`X/Y ±500`, `Z −500..100`) son los del ejemplo de
LinuxCNC y dejan sitio para un pivote de 250 mm; no son los de una máquina real.

## Comprobación automática

```bash
python3 tests/linuxcnc/check_sim.py
cat /tmp/indexedcam_sim.log
```

Arranca esta config en un display virtual (`Xvfb`), referencia (home) la
máquina, manda los cuatro planos por MDI y compara los joints con la tabla de
arriba. Termina en `PASS`. No toca ninguna máquina real.

Para lanzar además un programa completo (por ejemplo uno generado con
**Postprocesar**) y comprobar que se ejecuta entero:

```bash
python3 tests/linuxcnc/check_sim.py configs/linuxcnc/posted_example.ngc
```

Los tests rápidos (`tests/test_linuxcnc_config.py`) validan el INI, el HAL y que
cada plano de `validate_bc.ngc` sea exactamente el `LocalFrame` que IndexedCAM
calcula para esos ángulos B/C, además de que el intérprete `rs274` acepta el
programa.
