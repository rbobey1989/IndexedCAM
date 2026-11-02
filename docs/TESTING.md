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

Guarda el documento (`Ctrl+S`), ciérralo y ábrelo de nuevo: los setups se recuperan con `SetupManager(DocumentStorage(FreeCAD.ActiveDocument))`. Aparecen como el objeto `IndexedCAM_Setups` en el árbol.

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
4. Se muestra la triada local con B/C calculados; introduce el nombre del Setup (cancelar descarta la triada).
5. El Setup se guarda en el documento. `Ctrl+Z` lo deshace y `Ctrl+Y` lo rehace.

Sin selección válida aparece un aviso.

## Puente con el banco CAM (#12)

Las pruebas puras corren con `python3 -m pytest -q`. La comprobación dentro de FreeCAD (Job único, clones ligeros, alturas, recarga del archivo) se lanza con el AppImage; el log termina en `PASS`:

```bash
INDEXEDCAM_ROOT=$PWD INDEXEDCAM_LOG=/tmp/bridge.log \
  /home/rbobey1989/programas/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage tests/freecad/check_cam_bridge.py
cat /tmp/bridge.log
```

## Comando Assign Operation (#13)

Prueba manual (flujo completo):

1. Banco **IndexedCAM**, selecciona una cara y pulsa **Face Orientation** (nombre p. ej. `Lateral X`).
2. Repite con otra cara (otro Setup).
3. Pulsa **Assign Operation**: elige el Setup y el tipo de operación (Face, Pocket Shape, Profile, Adaptive).
4. Se abre el panel nativo de CAM con la cara del Setup ya como base. Acepta con OK; con Cancel la operación se elimina.
5. Cambia al banco **CAM**: hay un único Job con las operaciones de todos los Setups; cada trayectoria está en el sistema local de su Setup (cara en Z=0).

Comprobación automática dentro de FreeCAD (el log termina en `PASS`):

```bash
INDEXEDCAM_ROOT=$PWD INDEXEDCAM_LOG=/tmp/assign.log \
  /home/rbobey1989/programas/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage tests/freecad/check_assign_operation.py
cat /tmp/assign.log
```
