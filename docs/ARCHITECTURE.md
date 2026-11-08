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

La persistencia es intercambiable (`SetupStorage`). **Un Setup es un Job de CAM** (`IndexedCAM/Core/orientation_jobs.py`): el documento solo contiene Jobs —el del usuario y uno por orientación— y cada uno guarda su Setup en la propiedad oculta `IndexedCAMSetup`. `JobSetupsStorage` (`Core/document_storage.py`) lee la lista de Setups de esos Jobs y, al guardar, la reconcilia: un Setup nuevo crea su Job desde la pieza de sus metadatos, un renombrado cambia la etiqueta y uno borrado se lleva el Job con sus operaciones. El programa (`JobProgramStorage`) y los ajustes del post y de seguridad (`JobSettingStorage` y sus subclases) se guardan en propiedades ocultas de todos los Jobs de orientación y se leen del primero, así que borrar uno no pierde la configuración. No hay ningún objeto contenedor, y `Gui/job_view.py` da a esos Jobs el proveedor de vista de CAM para que sus grupos aparezcan dentro del Job. `Core/job_context.py` solo enumera los Jobs CAM del documento (para poder asignar sus operaciones). `MemoryStorage` se usa en tests.

## Visualización

`IndexedCAM/Gui/triad.py` dibuja el sistema XYZ local de un Setup como un nodo Coin3D (`IndexedCAM_Triad`) añadido al grafo de escena de la vista activa. La conversión del marco local a cuaternión es Python puro y está testeada; `pivy` solo se importa al mostrar la triada. `TriadView.show/clear` gestionan un único nodo temporal sin tocar el documento.

## Comandos

`Commands/face_orientation.py` contiene `FaceOrientationWorkflow` (sin dependencia de FreeCAD, con colaboradores inyectados): extrae la cara, calcula B/C (`Core/face_orientation.py`, que aplica la rotación del `Placement` de la pieza a la normal), previsualiza la triada, pide el nombre y añade el Setup dentro de una transacción deshacible. Al crear la orientación se eligen las operaciones CAM que se harán orientadas a ella (`OperationAssigner`, `Core/operation_assignment.py`). `Commands/assign_operation.py` asocia después otras operaciones existentes a una orientación. `Commands/context.py` construye, para el documento, gestor, programa, puente y asignador (`IndexedContext`). `Commands/rename_setup.py` (`RenameSetupWorkflow`) renombra el Job de la orientación y su modelo local **antes** de persistir el nombre nuevo (el guardado reconoce los Jobs por nombre) y actualiza el programa; la regla de validación de nombres es única (`SetupManager.name_error`) y la usan creación y renombrado. `Core/program.py` guarda el programa (pasos `(Setup, operación)` ordenados, en los Jobs de orientación), se sincroniza con los Jobs de orientación y `chain()` calcula, con `Core/path_endpoints.py`, la pose inicial y final de cada paso en coordenadas de pieza y si necesita transición. `Commands/program.py` lo muestra y reordena. `Core/transition_planner.py` (`TransitionPlanner`, `plan_program`) planifica la transición entre Setups distintos (retirada → esfera de seguridad → giro B/C → aproximación) y solo la devuelve si todas las muestras respetan los límites y un `CollisionChecker` inyectado (#17) no detecta colisión; si no, `TransitionError`. `Core/collision_checker.py` (`PartCollisionChecker`) implementa ese comprobador con `Part`: cilindros de la envolvente frente a obstáculos con `distToShape` y un margen; `check_operation` aplica la misma comprobación a los puntos de una trayectoria CAM. `Core/preview.py` (`PreviewBuilder`, `Clip`, `Playlist`) genera, sin FreeCAD, las muestras de herramienta de cada operación, de cada transición y de la retirada final con el cabezal de vuelta a vertical, con colisión perezosa por muestra; `Playlist` encadena los clips marcados por el usuario para reproducirlos de corrido. `Commands/preview.py` calcula el bruto del programa, pasa la esfera de seguridad al constructor y ofrece la lista con casillas; `Gui/tool_view.py` (`ToolView`) dibuja con Coin3D herramienta, portaherramientas, cabezal y trayectoria (nodos temporales) y `Commands/preview.py` ofrece el reproductor. `FaceOrientationCommand` lo conecta con la GUI y `InitGui.py` lo registra en la barra y el menú.

## Puente CAM

`IndexedCAM/Core/orientation_jobs.py` mantiene **un Job de CAM por orientación**: crea el `LocalModel` (`Core/local_model.py`, clon ligero con `Shape` transitorio y `Placement` = marco del Setup), lo recalcula, crea el Job (`Path.Main.Job.Create`) con ese modelo, deriva el bruto con `Stock.CreateFromBase` y guarda el Setup en JSON en el propio Job. Es la única forma de que las operaciones de área (Adaptive, 3D Surface, Waterline) calculen bien, porque leen `Job.Model` y `Job.Stock` e ignoran la geometría de la operación. `Core/cam_bridge.py` es la fachada: `attach_setup`, `bind_operation` (mueve la operación al Job, reapunta su `Base` a las mismas caras del modelo, reajusta `FinalDepth` y le da su propio controlador de herramienta), `refresh_operation` (alturas por expresión + `Placement` para dibujar sobre la cara), `detach_setup`, `stocks` y `candidates`. Ver [CAM_INTEGRATION.md](CAM_INTEGRATION.md).
