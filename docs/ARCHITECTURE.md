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

`Core/post_program.py` define el modelo independiente de la máquina: `PostTool`, `PostMove`, `PostOperation`, `PostOrientation` y `PostProgram`. `Core/post_builder.py` agrupa los pasos consecutivos de un mismo Setup en una orientación, adjunta herramienta, husillo y refrigerante a cada operación y calcula las dos alturas locales que necesita el G-code: `safe_z` (por encima de la misma esfera de seguridad que usa el Preview) y `clearance_z` (primera Z del camino). `Post/linuxcnc.py` renderiza el programa: por orientación retirada, `G69`, parada de husillo, cambio de herramienta (`M6` + `G43.4`), indexado `B`/`C`, plano inclinado `G68.2 P3` con el origen/+X y la normal del `LocalFrame`, aproximación y las operaciones **sin transformar** en coordenadas locales; `AxisSigns` mapea los ángulos de pieza a las palabras del controlador y `LinuxCNCConfig` reúne unidades, decimales, numeración de línea, refrigerante y cabecera. `Commands/post.py` conecta el comando con el documento y escribe el fichero. Ver [POST_LINUXCNC.md](POST_LINUXCNC.md).

## Gestión de setups

`SetupManager` (`IndexedCAM/Core/setup_manager.py`) mantiene una lista ordenada de `IndexedSetup` con nombres únicos (sin distinguir mayúsculas): `add`, `get`, `rename`, `delete`, `move`, `reorder`, `update` y `unique_name`. Cada operación valida antes de persistir, de modo que un error no altera el estado.

La persistencia es intercambiable (`SetupStorage`). `JobStorage` guarda las orientaciones **dentro del Job de CAM** que creó el usuario: un grupo `Orientations` (en `job.Group`, creado al primer guardado) con un grupo por orientación que contiene su modelo local (JSON oculto más B, C y origen de solo lectura). El programa se guarda en el mismo grupo (`JobProgramStorage`). Viaja dentro del `.FCStd`. `Core/job_context.py` resuelve el Job: el relacionado con la selección, el único del documento o el que elija el usuario; IndexedCAM nunca crea el Job. `DocumentStorage` (contenedor a nivel de documento) y `MemoryStorage` se usan en tests.

## Visualización

`IndexedCAM/Gui/triad.py` dibuja el sistema XYZ local de un Setup como un nodo Coin3D (`IndexedCAM_Triad`) añadido al grafo de escena de la vista activa. La conversión del marco local a cuaternión es Python puro y está testeada; `pivy` solo se importa al mostrar la triada. `TriadView.show/clear` gestionan un único nodo temporal sin tocar el documento.

## Comandos

`Commands/face_orientation.py` contiene `FaceOrientationWorkflow` (sin dependencia de FreeCAD, con colaboradores inyectados): extrae la cara, calcula B/C (`Core/face_orientation.py`), previsualiza la triada, pide el nombre y añade el Setup dentro de una transacción deshacible. Al crear la orientación se eligen las operaciones del Job que se harán orientadas a ella (`OperationAssigner`, `Core/operation_assignment.py`). `Commands/assign_operation.py` asocia después otras operaciones existentes a una orientación. `Commands/context.py` construye, para el Job elegido, gestor, programa, puente y asignador. `Commands/rename_setup.py` (`RenameSetupWorkflow`) renombra un Setup y propaga el cambio con `CamBridge.rename_setup` al modelo local y a las operaciones; la regla de validación de nombres es única (`SetupManager.name_error`) y la usan creación y renombrado. `Core/program.py` guarda el programa (pasos `(Setup, operación)` ordenados, en el grupo `Orientations` del Job), se sincroniza con el Job y `chain()` calcula, con `Core/path_endpoints.py`, la pose inicial y final de cada paso en coordenadas de pieza y si necesita transición. `Commands/program.py` lo muestra y reordena. `Core/transition_planner.py` (`TransitionPlanner`, `plan_program`) planifica la transición entre Setups distintos (retirada → esfera de seguridad → giro B/C → aproximación) y solo la devuelve si todas las muestras respetan los límites y un `CollisionChecker` inyectado (#17) no detecta colisión; si no, `TransitionError`. `Core/collision_checker.py` (`PartCollisionChecker`) implementa ese comprobador con `Part`: cilindros de la envolvente frente a obstáculos con `distToShape` y un margen; `check_operation` aplica la misma comprobación a los puntos de una trayectoria CAM. `Core/preview.py` (`PreviewBuilder`, `Clip`, `Playlist`) genera, sin FreeCAD, las muestras de herramienta de cada operación, de cada transición y de la retirada final con el cabezal de vuelta a vertical, con colisión perezosa por muestra; `Playlist` encadena los clips marcados por el usuario para reproducirlos de corrido. `Commands/preview.py` pasa la esfera de seguridad al constructor y ofrece la lista con casillas; `Gui/tool_view.py` (`ToolView`) dibuja con Coin3D herramienta, portaherramientas, cabezal y trayectoria (nodos temporales) y `Commands/preview.py` ofrece el reproductor. `FaceOrientationCommand` lo conecta con la GUI y `InitGui.py` lo registra en la barra y el menú.

## Puente CAM

`Core/cam_bridge.py` trabaja sobre un Job existente (`CamBridge(job)`): cada Setup aporta un `LocalModel` (`Core/local_model.py`, clon ligero con `Shape` transitorio y `Placement` = inversa del marco del Setup) y cada operación asociada mueve su `Base` a las mismas caras de ese clon y liga sus alturas por expresión. Ver [CAM_INTEGRATION.md](CAM_INTEGRATION.md).
