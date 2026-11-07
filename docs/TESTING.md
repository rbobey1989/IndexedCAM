# Probar IndexedCAM en FreeCAD

## Pruebas automáticas

Desde la raíz del repositorio:

```bash
python3 -m pytest -q
```

Estas pruebas validan la lógica Python independiente de FreeCAD.
El `FaceAnalyzer` se prueba con caras simuladas en pytest y se ha verificado
además con caras plana y esférica reales en FreeCAD 1.1.4.

## Instalar el Workbench en Linux

IndexedCAM incluye un registro mínimo para que FreeCAD lo muestre en la lista de
Workbenches. En FreeCAD 1.1, enlaza la raíz del repositorio en la carpeta de
addons versionada del usuario:

```bash
mkdir -p ~/.local/share/FreeCAD/v1-1/Mod
ln -s /ruta/al/IndexedCAM_WorkBench \
  ~/.local/share/FreeCAD/v1-1/Mod/IndexedCAM
```

Sustituye `/ruta/al/IndexedCAM_WorkBench` por la ruta donde clonaste el
repositorio (por ejemplo, `/home/usuario/proyectos/IndexedCAM_WorkBench`). Si el
enlace ya existe, no vuelvas a crearlo. Para quitar solo el enlace:

```bash
rm ~/.local/share/FreeCAD/v1-1/Mod/IndexedCAM
```

La carpeta `v1-1` corresponde a FreeCAD 1.1. Otras versiones pueden usar un
directorio de datos versionado diferente; comprueba `FreeCAD.getUserAppDataDir()`
desde la consola Python de esa instalación.

Reinicia FreeCAD y selecciona **IndexedCAM** en el selector de Workbench. El
Workbench todavía no tiene un comando gráfico; usa la consola para probar el
analizador de una cara seleccionada.

## Comprobar el solver desde la consola Python

Abre **View → Panels → Python console** y ejecuta:

```python
from IndexedCAM.Machine.bc_head import normal_to_bc

normal_to_bc((0, 0, 1))  # B=0, C=0
normal_to_bc((1, 0, 0))  # B=90, C=0
normal_to_bc((0, 1, 0))  # B=90, C=90
```

## Analizar una cara seleccionada

Selecciona exactamente una cara en la vista 3D y ejecuta en la consola:

```python
selection = Gui.Selection.getSelectionEx()
if len(selection) != 1 or len(selection[0].SubObjects) != 1:
    raise RuntimeError("Selecciona exactamente una cara")

from IndexedCAM.Core.face_analyzer import FaceAnalyzer

analysis = FaceAnalyzer().analyze(selection[0].SubObjects[0])
print("Normal:", analysis.normal)
print("Centro de masa:", analysis.center)
print("Área:", analysis.area)
print("Orientación topológica:", analysis.orientation)
print("Tipo de superficie:", analysis.surface_type)
print("Punto donde se evaluó la normal:", analysis.normal_point)
```

La normal se evalúa en el punto medio del rango paramétrico de la cara. En una
cara curva puede variar a lo largo de la superficie; el centro de masa se
devuelve por separado y no necesariamente coincide con el punto de evaluación.

Para validar cambios al código fuente sin reinstalar, cierra y vuelve a abrir
FreeCAD, o recarga el módulo en consola:

```python
import importlib
import IndexedCAM.Machine.bc_head as bc_head
importlib.reload(bc_head)
```

La recarga no actualiza automáticamente instancias de clases importadas con
`from ... import ...`; vuelve a importarlas después de recargar.

## Ciclo de desarrollo recomendado

1. Ejecuta los tests rápidos con `python3 -m pytest -q`.
2. Reinicia FreeCAD para probar la integración real con su intérprete y API.
3. Prueba las operaciones geométricas y visuales dentro de FreeCAD cuando estén
   implementadas.
4. Comprueba los cambios de GUI en un documento desechable antes de aplicarlos
   a un proyecto de usuario.

## Crear un Setup desde una cara seleccionada

Con una cara seleccionada (ver sección anterior):

```python
from IndexedCAM.Core.face_analyzer import FaceAnalyzer
from IndexedCAM.Core.orientation_solver import OrientationSolver
from IndexedCAM.Core.indexed_setup import IndexedSetup

face = Gui.Selection.getSelectionEx()[0].SubObjects[0]
analysis = FaceAnalyzer().analyze(face)
angles = OrientationSolver().solve(analysis.normal).angles
setup = IndexedSetup("Cara 1", analysis.normal, angles.b, angles.c, origin=analysis.center)
print(setup.to_dict())
print(setup.local_frame())
```

## Gestionar setups en el documento activo

```python
import FreeCAD
from IndexedCAM.Core.document_storage import DocumentStorage
from IndexedCAM.Core.setup_manager import SetupManager

manager = SetupManager(DocumentStorage(FreeCAD.ActiveDocument))
manager.add(setup)                 # el IndexedSetup de la sección anterior
manager.rename("Cara 1", "Lado X")
print(manager.names())
```

Guarda el documento (`Ctrl+S`), ciérralo y ábrelo de nuevo: los setups se recuperan con el mismo código. (Los comandos del banco usan `JobStorage(job)`: las orientaciones viven dentro del Job de CAM, grupo `Orientations`.)

## Mostrar la triada local de un Setup

Con el `setup` y el `analysis` de las secciones anteriores:

```python
from IndexedCAM.Gui.triad import TriadView, suggested_size

triad = TriadView()
triad.show(setup.local_frame(), suggested_size(analysis.area))
# ...
triad.clear()   # la retira de la vista 3D
```

Ejes: X rojo, Y verde, Z azul (eje de herramienta, apunta a la normal de la cara). La triada es solo un nodo Coin3D de la vista: no se guarda en el documento ni lo modifica. `show` reemplaza la triada anterior de esa instancia de `TriadView`.

## Comando Face Orientation

1. Reinicia FreeCAD y elige el banco **IndexedCAM**.
2. Selecciona una única cara en la vista 3D.
3. Pulsa **Face Orientation** (barra de herramientas o menú IndexedCAM).
4. Se muestra la triada local con B/C calculados; introduce el nombre del Setup (cancelar descarta la triada) y marca las operaciones del Job que se orientarán a él.
5. El Setup se guarda en el Job (requiere un Job creado en CAM). `Ctrl+Z` lo deshace y `Ctrl+Y` lo rehace.

Sin selección válida aparece un aviso.

## Puente con el banco CAM (#12)

Las pruebas puras corren con `python3 -m pytest -q`. La comprobación dentro de FreeCAD (Job de CAM, clones ligeros, alturas, recarga del archivo) se lanza con el AppImage; el log termina en `PASS`:

```bash
INDEXEDCAM_ROOT=$PWD INDEXEDCAM_LOG=/tmp/bridge.log \
  /home/rbobey1989/programas/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage tests/freecad/check_cam_bridge.py
cat /tmp/bridge.log
```

## Flujo completo con el Job nativo (Face Orientation + Assign Operation)

1. Banco **CAM**: crea un **Job** con tu pieza y añade operaciones (Face, Pocket, Profile…) con su herramienta, como siempre.
2. Banco **IndexedCAM**: selecciona una cara y pulsa **Face Orientation**. Si el documento tiene varios Jobs se elige a cuál pertenece (se deduce de la selección si la pieza solo está en uno).
3. Escribe el nombre y marca las operaciones del Job que quieres mecanizar orientadas a esa cara (puedes dejarlas sin marcar).
4. En el árbol aparece el grupo **Orientations** junto al Job, con un objeto por orientación (B, C y origen). Las operaciones marcadas tienen la propiedad `IndexedSetup` y su Base está en el clon local (`IndexedCAM_Local_<nombre>`, en el grupo `Orientations`, no en `Job.Model` para no deformar el material en bruto del Job).
5. **Assign Operation** asocia después otras operaciones a una orientación existente. En CAM cada trayectoria está en el sistema local de su Setup (cara en Z=0).

Sin Job, los comandos avisan de que hay que crearlo antes en el banco CAM.

Comprobación automática dentro de FreeCAD (el log termina en `PASS`):

```bash
INDEXEDCAM_ROOT=$PWD INDEXEDCAM_LOG=/tmp/assign.log \
  /home/rbobey1989/programas/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage tests/freecad/check_assign_operation.py
cat /tmp/assign.log
```

## Nombre y renombrado de Setups

- **Face Orientation** pide el nombre al crear el Setup (por defecto `Setup`, `Setup 2`…). Un nombre vacío o repetido se rechaza con un aviso y se vuelve a preguntar.
- **Rename Setup**: elige el Setup y escribe el nuevo nombre (el botón OK se desactiva si es inválido). Se actualizan, en una sola transacción deshacible (Ctrl+Z), el Setup guardado, la etiqueta de su modelo local (`IndexedCAM_Local_<nombre>`) y la propiedad `IndexedSetup` de todas sus operaciones CAM. Los nombres internos de objeto no cambian, así que las expresiones y los enlaces de CAM siguen válidos.
- `tests/freecad/check_assign_operation.py` comprueba el renombrado y su persistencia tras guardar y reabrir.

## Programa de operaciones (#14)

Pulsa **Program** en la barra IndexedCAM: lista los pasos en orden (`Setup → operación`) indicando si el paso parte de la posición segura inicial, continúa del anterior o requiere una transición B/C (entre Setups distintos). **Subir/Bajar** reordena (deshacible). El programa se sincroniza solo con el Job: las operaciones nuevas se añaden al final, las eliminadas desaparecen y el renombrado de un Setup se refleja. Las transiciones en sí se planifican en #16.

La comprobación `tests/freecad/check_assign_operation.py` cubre el programa (orden, poses en coordenadas de pieza, renombrado, guardado y reapertura).

## Simulacion LinuxCNC (cabezal B+C)

El repositorio trae una maquina simulada con la cinematica `5axiskins` para
probar el 3+2 sin tocar hierro. Instrucciones completas y valores esperados en
[configs/linuxcnc/README.md](../configs/linuxcnc/README.md).

```bash
linuxcnc configs/linuxcnc/indexedcam.ini     # GUI Axis + ventana 3D del cabezal
```

Abre `validate_bc.ngc`: al pulsar Cycle Start la herramienta se orienta en las
cuatro caras del ejemplo. Despues de cambiar el postprocesador, un programa
generado con **Postprocesar** se puede abrir desde la misma GUI.

Comprobacion automatica (arranca la config en un display virtual, referencia la
maquina y compara los joints con la cinematica del pivote):

```bash
python3 tests/linuxcnc/check_sim.py
cat /tmp/indexedcam_sim.log          # ultima linea: PASS
```

Con argumentos ejecuta ademas esos programas y exige que **no haya errores del
controlador** (los lee del canal de errores NML) y que la maquina se mueva:

```bash
python3 tests/linuxcnc/check_sim.py \
    configs/linuxcnc/validate_bc.ngc \
    configs/linuxcnc/validate_tools.ngc \
    configs/linuxcnc/posted_example.ngc
```

Los tests rapidos validan ademas que el INI, el HAL y los planos de
`validate_bc.ngc` sean coherentes, que `rs274` acepte el programa y que **todos
los movimientos** de los programas de ejemplo quepan en los limites del INI
(`tests/test_linuxcnc_config.py`, sin necesidad de arrancar la maquina).

Dos avisos utiles:

- El realtime es unico: cierra cualquier otra instancia de LinuxCNC antes de
  ejecutar `check_sim.py` (el script lo detecta y sale con codigo 2).
- Un programa puede retirar por encima del recorrido Z+ de la configuracion. El
  error tipico es `Linear move on line N would exceed Z's positive limit`; el
  test de recorridos lo detecta sin abrir LinuxCNC.

## Postprocesado (#19)

Pulsa **Seguridad** para fijar la altura de retirada de los giros (0 mm =
mínima; la usan el Preview y el G-code) y **Postprocesar** (requiere operaciones
asignadas) para elegir el fichero `.ngc`. Genera un plano inclinado `G68.2` por orientación, el
indexado `B`/`C`, la retirada antes de cada giro y las operaciones en
coordenadas locales. Detalles y configuración de LinuxCNC en
[POST_LINUXCNC.md](POST_LINUXCNC.md).

```bash
INDEXEDCAM_ROOT=$PWD INDEXEDCAM_LOG=/tmp/post.log \
  /home/rbobey1989/programas/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage tests/freecad/check_post.py
cat /tmp/post.log
```

`check_post.py` crea un Job con dos orientaciones y comprueba, **leyendo el
G-code generado**, que el marco que reconstruye el controlador a partir de los
dos bloques `G68.2 P3` coincide con el `LocalFrame` del Setup (origen, +X,
normal y el +Y derivado), que la cabeza se indexa a los ángulos de cada Setup,
que hay un solo cambio de herramienta cuando se repite la herramienta, que la
retirada va antes de anular el plano y que los movimientos se emiten sin
transformar. Los tests rápidos (`tests/test_post_builder.py`,
`tests/test_linuxcnc_post.py`) cubren el modelo y el formato, incluido el
programa completo esperado.

## Previsualización (#18)

Pulsa **Preview** en la barra IndexedCAM (requiere operaciones asignadas, ver Programa). Se abre una ventana no modal con la lista de pasos: cada operación y, entre Setups distintos, su transición. Al elegir una entrada se dibuja su trayectoria (azul) y la herramienta (naranja), el vástago, el portaherramientas y el cabezal con la pose B/C de la muestra. **Deslizador** y **▶ Reproducir** recorren las muestras; si una muestra colisiona, la herramienta se pinta de **rojo** y el estado indica el obstáculo. **Buscar colisiones** salta a la primera muestra con colisión. Las transiciones que no se pudieron validar se marcan con ⚠ y se muestra la ruta intentada. Al cerrar la ventana se limpia la vista 3D.

Notas: la transición se valida con la herramienta del paso al que llega; los obstáculos son la pieza (el bruto y el utillaje aún no se definen desde la interfaz). La comprobación en FreeCAD (`check_assign_operation.py`) cubre clips, escena 3D y ventana.
