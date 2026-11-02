 # Arquitectura

## Setup

Un **Setup** representa una orientación indexada de la pieza. Contiene:

- **Nombre**: identificador del setup.
- **Normal**: normal unitaria de la superficie (dirección del eje de herramienta, en coordenadas de pieza).
- **WCS**: sistema de coordenadas de trabajo (por defecto `G54`) y origen del setup.
- **Sistema XYZ local**: derivado de `Rz(C) @ Ry(B)`; su Z coincide con la normal.
- **B y C**: ángulos de los ejes rotativos del cabezal B+C (no hay eje A).
- **Operaciones** y **metadatos** serializables (JSON).

Implementación: `IndexedCAM/Core/indexed_setup.py` (`IndexedSetup`, `to_dict`/`from_dict`).

## Operación

Cada setup agrupa las operaciones CAM que se ejecutan en esa orientación. Las operaciones se interpretan con respecto al sistema XYZ local del setup.

## Postprocesado

El postprocesador genera los movimientos de posicionamiento necesarios antes de las operaciones de cada setup. Estos movimientos llevan la máquina a los ángulos B y C asociados al setup.

## Gestión de setups

`SetupManager` (`IndexedCAM/Core/setup_manager.py`) mantiene una lista ordenada de `IndexedSetup` con nombres únicos (sin distinguir mayúsculas): `add`, `get`, `rename`, `delete`, `move`, `reorder`, `update` y `unique_name`. Cada operación valida antes de persistir, de modo que un error no altera el estado.

La persistencia es intercambiable (`SetupStorage`). `DocumentStorage` guarda el JSON de los setups en un objeto `App::FeaturePython` llamado `IndexedCAM_Setups`, que se crea solo al primer guardado y viaja dentro del `.FCStd`. `MemoryStorage` se usa en tests.

## Visualización

`IndexedCAM/Gui/triad.py` dibuja el sistema XYZ local de un Setup como un nodo Coin3D (`IndexedCAM_Triad`) añadido al grafo de escena de la vista activa. La conversión del marco local a cuaternión es Python puro y está testeada; `pivy` solo se importa al mostrar la triada. `TriadView.show/clear` gestionan un único nodo temporal sin tocar el documento.

## Comandos

`Commands/face_orientation.py` contiene `FaceOrientationWorkflow` (sin dependencia de FreeCAD, con colaboradores inyectados): extrae la cara, calcula B/C (`Core/face_orientation.py`), previsualiza la triada, pide el nombre y añade el Setup dentro de una transacción deshacible. `FaceOrientationCommand` lo conecta con la GUI y `InitGui.py` lo registra en la barra y el menú.
