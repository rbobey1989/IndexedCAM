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
