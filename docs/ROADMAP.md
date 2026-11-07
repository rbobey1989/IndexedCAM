# Plan de desarrollo

Una fase cada vez; cada fase cierra con código, tests y docs. La lógica matemática no depende de FreeCAD; los adaptadores geométricos usan objetos de su API y se verifican también dentro de FreeCAD.

| Fase | Issues | Entregable | Estado |
| --- | --- | --- | --- |
| 0 | — | Registro básico del Workbench y ciclo de pruebas en FreeCAD | Hecha |
| 1 | #1, #10 | Cinemática normal → B/C (`Machine/bc_head.py`) + tests | Hecha |
| 2 | #2 | `FaceAnalyzer` (FreeCAD): normal representativa, centro, área y orientación | Hecha |
| 3 | #6 | `BCMachine`: límites (B 0..180, C ±360), vector de herramienta, validación | Hecha |
| 4 | #3 | `OrientationSolver`: normal → orientación válida para la máquina (elige solución dentro de límites) | Hecha |
| 5 | #4 | Modelo `Setup` (nombre, normal, WCS, B, C, operaciones, metadatos) | Hecha |
| 6 | #7 (#8 cerrada como duplicada) | `SetupManager`: crear/renombrar/borrar/ordenar en el documento | Hecha |
| 7 | #5 | Triada XYZ local con Coin3D | Hecha |
| 8 | #9 | Comando "Face Orientation" + registro del Workbench (`InitGui.py`) | Hecha |
| 9 | #11 | Investigación de integración con CAM (sin tocar el core): ver [CAM_INTEGRATION.md](CAM_INTEGRATION.md) | Hecha |
| 10 | #12 | Puente Setup ↔ Job CAM (clon local por Setup, alturas por operación) | Hecha |
| 11 | #13 | Comando "Asignar operación" | Hecha |
| 11b | — | Rediseño Job-first: el Job lo crea el usuario en CAM, las orientaciones viven dentro de él y se les asocian operaciones existentes | Sustituido en la fase 20 |
| 12 | #14 | Programa: secuencia de pasos encadenados | Hecho |
| 13 | #15 | Envolvente de herramienta/cabezal en la máquina | Hecho |
| 14 | #16 | `TransitionPlanner` (retirada, giro, aproximación) | Hecho |
| 15 | #17 | `CollisionChecker` | Hecho |
| 16 | #18 | Visualización de herramienta/movimientos y reproductor | Hecho |
| 17 | #19 | Postprocesador LinuxCNC (planos `G68.2` + B/C + `5axiskins`): ver [POST_LINUXCNC.md](POST_LINUXCNC.md) | Hecho |
| 18 | — | Configuracion de simulacion LinuxCNC (cabezal B+C, `5axiskins`) y verificacion de los planos: ver [configs/linuxcnc](../configs/linuxcnc/README.md) | Hecho |
| 19 | — | Distancia de seguridad configurable (0 mm por defecto) y avance garantizado en el G-code: `Commands/safety.py`, `Post/linuxcnc.py` | Hecho |
| 20 | — | **Un Job de CAM por orientación** (`Core/orientation_jobs.py`): modelo y bruto en el marco del Setup, operaciones movidas a su Job y controlador propio. Es lo que hace funcionar Adaptive y 3D Surface en caras inclinadas; ver [CAM_INTEGRATION.md](CAM_INTEGRATION.md) | Hecho |

## Decisiones

- **Un Job por orientación** (fase 20). CAM calcula las operaciones de área contra `Job.Model` y `Job.Stock` e ignora la geometría de la operación, así que compartir un Job entre orientaciones solo funciona para 2.5D. Medido en `Test000.FCStd`: un `3D Surface` en la cara inclinada daba una trayectoria desplazada y con Z positiva; en su propio Job da la trayectoria correcta sobre la cara.
- Solver puro devuelve B∈[0,180], C∈[−180,180); los límites físicos los valida `BCMachine` (fase 3).
- El Setup guarda solo B y C (A ausente), los docs `ARCHITECTURE.md` y `MVP.md` ya no mencionan A.
- B por defecto 0..180 (coincide con la salida del solver; C decide la dirección y B solo la inclinación). Los límites son configurables: una máquina limitada a 90° usa `AxisLimits(0, 90)` y entonces las normales con nz<0 son inalcanzables.
- `FaceAnalyzer` devuelve el centro de masa y una normal unitaria evaluada en el punto medio del rango paramétrico; para caras curvas son datos representativos, no una normal constante en toda la cara.
