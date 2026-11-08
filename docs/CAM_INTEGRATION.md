# Integración con el banco CAM de FreeCAD (#11)

Estrategia para añadir 3+2 sobre el banco CAM **sin modificar** FreeCAD ni CAM. Solo se usan APIs públicas de Python.

## Hechos verificados (FreeCAD 1.1.4)

Marcados como *probado* (ejecutado en el AppImage) o *código* (leído en `Mod/CAM/Path`).

| Hecho | Origen |
| --- | --- |
| Un Job admite varios clones rotados (`Model.addObject`) y operaciones con Base en cada uno; el bruto es único y hay que fijar alturas por operación. | probado |
| Las operaciones CAM generan trayectorias 3 ejes en el marco del Job (plano de trabajo = XY, herramienta = +Z). No existe plano de trabajo inclinado. | código |
| Si el modelo de un Job se coloca con la rotación inversa del marco del Setup, `MillFace` sobre la cara inclinada genera Z constante (probado: cara con normal +X → `G1 … Z60`). | probado |
| `Path.Command` admite `B` y `C` (`G0 B90.000000 C0.000000 X1.000000`). | probado |
| `Job.Fixtures` (G54…) repite **todas** las operaciones por cada fixture (`_buildPostList`); no sirve para asignar operaciones distintas a cada Setup. | código |
| `PostProcessorFactory` busca `<nombre>_post.py` en las rutas de post y en `sys.path`, y usa la clase `<Nombre>` (`postname.title()`). El directorio del addon ya está en `sys.path`, así que `indexedcam_post.py` en la raíz es descubrible. | probado + código |
| Las operaciones se crean por API: `Path.Op.<Tipo>.Create(nombre, parentJob=job)` y se asignan caras con `op.Base = [(objeto, ['FaceN'])]`. | probado |
| Cada operación expone `op.Path.Commands` tras `recompute()`; el `Job` expone `Operations.Group` y `ToolController`. | probado |
| Las operaciones de área (Adaptive, 3D Surface, Waterline) leen **siempre** `Job.Model` y `Job.Stock`: `Area.areaOpShapeForDepths` devuelve `job.Stock.Shape`, `Base.__init__` hace `self.stock = parentJob.Stock` y `SurfaceSupport._identifyFacesAndVoids` solo reconoce caras de objetos que estén en `Job.Model.Group` (`mdlIdx = None` en otro caso). | código |
| Por eso un único Job no puede mecanizar una cara inclinada con OCL: la geometría local y el bruto del Job están en marcos distintos. Medido en `Test000.FCStd`: `Surface` daba 215 comandos entre X 2,5..7 y **Z −1,7..+5**; el mismo op en un Job cuyo modelo es el clon local da 305 comandos sobre la cara, con Z ≈ 0 y profundidad −1,4. | probado |
| `Path.Main.Job.Create(nombre, [modelo])` **clona** el modelo (`Draft.clone` → objeto «Model-Clone») y `Stock.CreateFromBase(job)` deriva el bruto de ese clon. | probado |
| `Draft.clone` copia la forma en el momento de crearlo: el modelo local debe estar ya recalculado (`recompute`) antes de crear el Job. | probado |
| `Job.Tools.addObject(tc)` **quita** el controlador del Job anterior (`InList` pasa al nuevo `Tools`): las tablas de herramientas no se comparten. `Job.Proxy.addOperation`/`addToolController` son la API pública para mover operaciones. | probado |
| `Face.normalAt()` devuelve la normal en el marco propio de la forma, **sin** su `Placement`, mientras que `CenterOfMass`/`BoundBox` sí lo incluyen; con una pieza con `Placement` hay que rotar la normal a mano. | probado |

## Decisión (revisada): un Job de CAM por orientación

Las operaciones 2.5D se conforman con la `Base` de la operación, pero las de
área (Adaptive, 3D Surface, Waterline) **no**: leen `Job.Model` y `Job.Stock`
(tabla de hechos, arriba). Un único Job cuyo modelo es la pieza no puede
mecanizar una cara inclinada, porque el CAM seguiría calculando con la
herramienta en el +Z de la **pieza**. Por eso cada Setup tiene su propio Job,
con el modelo ya colocado en el marco del Setup y un bruto derivado de él:

```
Documento
├─ Job                (el del usuario, intacto)
├─ <setup> B… C…      Job CAM de la orientación, en la raíz como cualquier Job
│  ├─ Operations…     las operaciones del Setup
│  ├─ Model…          clon del modelo local (cara mecanizada en Z=0)
│  ├─ Stock…          caja de ese clon
│  ├─ SetupSheet…
│  ├─ Tools…          su tabla de herramientas
│  └─ IndexedCAM_Local_<setup>   modelo local (Shape transitorio)
└─ …
```

Reglas derivadas (todas verificadas en 1.1.4):

- `OrientationJobs` (`Core/orientation_jobs.py`) crea y mantiene los Jobs: modelo
  local → `recompute` → `Path.Main.Job.Create` → `Stock.CreateFromBase` →
  etiqueta `"<setup> B… C…"` → propiedad `IndexedCAMSetup` con el Setup en JSON
  (el Job es autodescriptivo y así se encuentra por nombre).
- Al asociar una operación (`CamBridge.bind_operation`) se **mueve** al Job de la
  orientación (`Operations.removeObject` + `Job.Proxy.addOperation`), se
  reapunta su `Base` a las **mismas caras** del modelo del Job (los nombres
  `FaceN` se conservan) y se le da su propio controlador de herramienta:
  `Tools.addObject` expulsaría el controlador del Job de origen y ese Job se
  quedaría sin herramienta para crear más operaciones.
- `FinalDepth` es una Z local: al mover la operación se reajusta conservando la
  **profundidad bajo la cara** (`final - (start_viejo - top_nuevo)`), que es lo
  que pidió el usuario. `StartDepth`, `SafeHeight` y `ClearanceHeight` se ligan
  por expresión al `Shape.BoundBox.ZMax` del modelo del Job.
- Las alturas y el bruto salen del modelo del propio Job: la cara mecanizada
  queda en **Z local = 0** en todas las orientaciones.
- `Placement` de la operación = inversa del marco del Setup: se sigue dibujando
  la trayectoria sobre la cara que mecaniza. `Path.Commands` permanece en el
  marco local (lo que usan programa, preview y post).
- **El árbol es el de CAM.** Un Job creado desde Python no recibe el proveedor
  de vista de CAM, y sin él sus grupos (`Operations…`, `Model…`, `Tools…`,
  `SetupSheet…`) aparecen sueltos en la raíz en lugar de anidados dentro del
  Job. `Gui/job_view.py` asigna `Path.Main.Gui.Job.ViewProvider` (más la
  extensión `Gui::ViewProviderGroupExtensionPython`) y una subclase que añade el
  modelo local a `claimChildren`, de modo que el Job se ve exactamente igual que
  uno creado desde CAM y el único objeto añadido queda dentro. El proveedor
  viaja en el `GuiDocument.xml`, y `Gui/restore_observer.py` lo vuelve a asignar
  al abrir documentos antiguos.
- **No hay contenedor.** Los `IndexedSetup` son los propios Jobs: su lista es la
  que manda (`Core/document_storage.py::JobSetupsStorage`), así que añadir un
  Setup crea su Job, renombrarlo cambia la etiqueta y borrarlo se lleva el Job
  con sus operaciones. El programa y los ajustes del post y de seguridad se
  guardan en propiedades ocultas de **todos** los Jobs de orientación y se leen
  del primero, de forma que borrar uno no pierde la configuración. Los documentos
  del esquema anterior (grupo `IndexedCAM`) se adoptan solos al abrirlos.

### Por qué cambió (historial)

Segunda revisión del árbol (esta): la primera versión de esta arquitectura
guardaba los Jobs y los modelos locales dentro de un grupo `IndexedCAM` y los
creaba sin proveedor de vista, así que en el árbol cada Job aparecía como
`IndexedCAM > <setup>` con `Operations…`, `Model…`, `Tools…` y `SetupSheet…`
sueltos al mismo nivel. Ahora los Jobs son objetos de la raíz con sus grupos
dentro y el documento no gana ningún objeto contenedor.

La primera versión añadía las orientaciones **dentro** del Job del usuario: un
clon local por Setup en un grupo aparte y las operaciones con `Base` en ese
clon, con alturas por expresión. Funcionaba para 2.5D (`MillFace`, `Pocket`,
`Profile`, `Adaptive` en caras horizontales), pero con `3D Surface` sobre una
cara inclinada la trayectoria salía desplazada y con Z positiva: CAM mezclaba
el `Job.Stock` (coordenadas de pieza) con la geometría local del `Base`, y
`SurfaceSupport` ni siquiera encontraba las caras (`mdlIdx = None`). El cálculo
se hacía, además, contra el modelo del Job —la pieza sin girar—, así que el
resultado no podía ser correcto. La alternativa «un Job por Setup» que se había
descartado por «multiplicar Jobs» es la única que mantiene un solo marco para
modelo, bruto y operaciones.

### Clones ligeros (`LocalModel`)

Un clon por Setup no debe pesar ni en memoria, ni en el archivo, ni en la recomputación. Medido en FreeCAD 1.1.4 con una pieza de 144 taladros y 4 clones:

| Variante | Tamaño `.FCStd` |
| --- | --- |
| Sin clones | 24 KB |
| Clones con `Shape` guardado (copia o compartido) | 105 KB (cada clon guarda su BREP) |
| **`LocalModel` con `Shape` transitorio** (2 clones, pieza simple) | 31 KB |

Diseño adoptado:

- `LocalModel` es un `Part::FeaturePython` con un proxy del addon y propiedades `Source` (enlace al modelo) y `Normal`/Setup.
- La transformación Placement es la inversa del marco local del Setup (`Core/local_placement.py`, matemática pura y testeada): `p_local = Rᵀ (p − origen)`, no la rotación de arco mínimo, para coincidir con la triada y con el post.
- `execute`: `shape = Source.Shape.copy(False)` (**comparte la geometría**, no la duplica), `obj.Shape = shape` y `obj.Placement = rotación del Setup` (hay que fijar el `Placement` del objeto; poner la rotación en el `Shape` no basta).
- `Shape` se marca `Transient`: **no se guarda en el archivo**. Al cargar, `onDocumentRestored` reconstruye la forma directamente (un `touch()` no basta: el clon quedaba con forma nula).
- Memoria: una única geometría compartida por todos los clones; solo cambia la ubicación.
- Los clones dependen de `Source`, así que siguen los cambios paramétricos del modelo sin sincronización manual (resuelve el riesgo abierto de sincronización).
- Verificado: cada modelo local se puede usar como `Model` de un Job (CAM lo clona) con la cara del Setup en Z=0; guardar, reabrir y recalcular restaura modelos, Jobs y operaciones.

Descartado: `App::Link` como modelo (el Job lo acepta pero crea su propio clon interno, sin ahorro) y clones con `Shape` persistente (archivo proporcional al número de Setups).

Optimización futura si fuese necesario: modo "solo caras" (clon con únicamente la cara del Setup) para operaciones 2.5D en piezas muy pesadas; las operaciones 3D requieren el modelo completo.
- La relación operación → Setup la da el Job que la contiene (`OrientationJobs.setup_of_operation`); `IndexedSetup.operations` y el programa se sincronizan desde ahí.
- El orden de salida lo define el programa de IndexedCAM, no `Job.Fixtures` ni `OrderOutputBy`.
- Verificado: `Adaptive` y `Pocket` funcionan sobre el clon local; al editar el modelo original el clon se actualiza solo; 4 clones de una pieza de 150 caras recalculan en ~1 s. Los dressups (Boundary, Tags…) no se han probado todavía.

### Hallazgos de la implementación (#12, #13)

- La `Base` de una operación nativa apunta al clon propio del Job (`Model-<pieza>`), no a la pieza original; los nombres de cara (`FaceN`) coinciden, así que al asociarla se reasigna a las mismas caras del modelo del Job de la orientación.
- Una operación o un Setup pueden borrarse en CAM en cualquier momento, por eso `IndexedSetup.operations` y el programa se sincronizan desde los Jobs (`bound_steps`).
- El Job de la orientación es un objeto de la raíz con sus grupos dentro: en el árbol no se distingue de un Job creado desde CAM (`Gui/job_view.py`), y el modelo local se mantiene oculto (`Gui/restore_observer.py`).
- La cara del Setup queda en Z=0 local y el centro de la cara en el origen XY del WCS.
- Limitación corregida: hasta ahora se ignoraba el `Placement` de la pieza al leer la normal de la cara y una pieza desplazada/girada daba B/C erróneos; `FaceAnalyzer.analyze(face, rotation)` aplica ahora la rotación del objeto.

## Flujo de usuario

1. En el banco **CAM**: crear las operaciones como siempre (con su herramienta), en cualquier Job. También vale crearlas ya dentro del Job de la orientación.
2. En **IndexedCAM**: seleccionar una cara → **Face Orientation**. Se calcula B/C, se muestra la triada, se pide el nombre y se crea el **Job de la orientación** con su modelo local y su bruto.
3. En el mismo comando se marcan las operaciones que se harán orientadas a ella (opcional; **Assign Operation** lo permite después). Cada operación se mueve a ese Job, apunta a las mismas caras de su modelo y hereda sus alturas.
4. El programa es una lista ordenada de pasos `(Setup, Operación)`; cada paso continúa desde el punto final del anterior y el primero parte de la posición segura inicial.
5. Entre dos pasos de distinto Setup se inserta una **transición** (retirada → giro B/C → aproximación) validada sin colisiones.
6. En todo momento se muestra la **orientación de la herramienta** y los movimientos (ver Visualización).


## Transiciones sin colisión

Entradas: pose final del paso anterior `(B₁,C₁, punta P₁)`, pose inicial del siguiente `(B₂,C₂, P₂)`, geometría de obstáculos (modelo, material en bruto, utillaje) y envolvente de la herramienta.

Algoritmo (puro, testeable sin FreeCAD salvo el comprobador):

1. **Retirada** del paso anterior a lo largo de su eje de herramienta hasta fuera de la esfera de seguridad.
2. **Esfera de seguridad**: centro = centro del bruto, radio = semidiagonal del bruto + longitud de herramienta/portaherramientas + margen. Con la punta sobre la esfera y la herramienta apuntando radialmente hacia fuera, la herramienta no puede entrar en la pieza.
3. **Giro**: interpolar B/C (paso ≤ 2°) y mover la punta sobre la esfera: `P(t) = c + n(B(t),C(t))·R`. Respetar los límites de `BCMachine`.
4. **Aproximación** radial hasta el punto de entrada de la siguiente operación.
5. **Comprobación**: en cada muestra se construye la envolvente (herramienta + portaherramientas + cabezal) y se comprueba la distancia mínima a cada obstáculo (`Shape.distToShape`) ≥ margen; también los límites de carrera de los ejes lineales.
6. Si falla, probar en orden: alternativas del solver (C+180 con −B, equivalentes ±360), sentido de giro contrario de C, esfera mayor. Si ninguna es válida, **error explícito** con la muestra y el obstáculo; nunca se emite una transición sin validar.

La verificación de colisiones dentro de una operación (cabezal inclinado frente a paredes) reutiliza el mismo comprobador sobre los puntos de `op.Path`.

## Visualización

- `ToolView` (Coin3D, como `TriadView`): modelo simplificado de herramienta + portaherramientas + cabezal con la pose actual (B/C), y la polilínea de la trayectoria transformada a global. Nodos temporales, no se guardan en el documento.
- Se actualiza al seleccionar Setup, operación o transición; en transición, un **reproductor** (deslizador + play) recorre las muestras y colorea en rojo las que colisionan.
- Los datos de máquina (pivote de B, longitud/radio del cabezal) se añaden a la definición de máquina; son necesarios para la envolvente y el TCP.

## Postprocesado

`indexedcam_post.py` (clase `Indexedcam`) recorre el programa y, por paso: emite posicionamiento B/C tras la retirada, selecciona el WCS y las coordenadas de las operaciones. Dos modos, configurables por máquina:

- **Local** (controladores con inclinación de plano: G68.2/G254, CYCLE800, PLANE): se emiten XYZ locales.
- **Máquina** (TCP/G43.4): el post transforma XYZ locales → máquina con la cinemática de `bc_head`.

Modo inicial recomendado: *Máquina*, por ser matemática pura y testeable. Los signos y ceros reales dependen del controlador (ya anotado en `MACHINE.md`).

## Módulos propuestos

| Módulo | Responsabilidad | Depende de FreeCAD |
| --- | --- | --- |
| `Core/program.py` | Secuencia ordenada de pasos y punto final de cada uno | no |
| `Core/local_placement.py` | Transformación parte → marco local y alturas por operación | no |
| `Core/local_model.py` | Clon ligero `LocalModel` por Setup | sí |
| `Core/orientation_jobs.py` | Un Job CAM por orientación (`create`, `ensure`, `rename`, `remove`, `bound_steps`) | sí |
| `Core/cam_bridge.py` | Fachada de los Jobs: `attach_setup`, `bind_operation`, `refresh_operation`, `refresh_all`, `detach_setup`, `stocks` | sí |
| `Gui/job_view.py` | Proveedor de vista del Job (grupos anidados + modelo local) | sí |
| `Core/transition_planner.py` | Retirada, giro sobre esfera, aproximación, alternativas | no |
| `Core/collision_checker.py` | Interfaz + implementación con `Part` | sí (implementación) |
| `Machine/envelope.py` | Herramienta, portaherramientas, cabezal, pivote | no |
| `Gui/tool_view.py` | Visualización y reproductor | sí |
| `Commands/assign_operation.py` | Comando "Asignar operación" | sí |
| `Post/indexedcam_post.py` | Postprocesador | no (usa `Path`) |

## Riesgos abiertos

- Rendimiento de recomputación con modelos muy pesados (mitigación: modo "solo caras").
- Forma real de herramienta/portaherramientas: las toolbits de CAM pueden traer `Shape`; si no, se usa cilindro/cono simplificado.
- Signos, ceros y pivote reales por máquina.
- Operaciones 3D (Surface/Waterline) con cabezal inclinado exigen comprobación de colisión dentro de la operación.

## Estado de la planificación (#16)

`Core/transition_planner.py` implementa los pasos 1–6 anteriores con un `CollisionChecker` inyectable (`collision(punta, B, C) -> Optional[str]`; la implementación con `Part` es #17). Alternativas, por este orden: equivalentes del solver más cercanos primero (C±360°, y (−B, C+180°) si la máquina admite B negativo) y después esfera 1.5× mayor. Muestreo: ≤2° en B/C y 5 mm en tramos lineales. Sin alternativa válida lanza `TransitionError` con la fase, la posición y el obstáculo; nunca devuelve una transición sin validar.

## Comprobador de colisiones (#17)

`PartCollisionChecker(envelope, obstacles, margen=2 mm)` (`Core/collision_checker.py`). Obstáculos en coordenadas de pieza: la pieza y el bruto (*cortables*) y el utillaje. `checker_for_operation(bridge, pieza, operación, envolvente_base, bruto=None, utillaje=())` lo construye con la herramienta real de la operación. El bruto no se toma de los Jobs: cada uno está en el marco de su orientación; si se necesita, se pasa explícitamente en coordenadas de pieza. Dos modos:

- `collision(punta, B, C)`: tránsito; todos los cilindros contra todos los obstáculos.
- `cutting_collision(...)`: mecanizado; solo la parte cortante (`CuttingEdgeHeight`) puede tocar lo cortable. El vástago (resto de la herramienta, con `ShankDiameter`), el portaherramientas y el cabezal no, y el utillaje se comprueba contra todo.

`check_operation(check, op.Path.Commands, frame, B, C)` recorre la trayectoria (puntos cada ≤5 mm; los arcos G2/G3 con I/J se teselan) y devuelve el primer choque con su posición.

**Carrera lineal:** `BCMachine.travel` (`TravelBox`, opcional) limita la posición del pivote de B en coordenadas de pieza (se asume G54 en el origen de la pieza); el planificador rechaza muestras fuera de la caja ("fuera de la carrera lineal").

Verificado con `tests/freecad/check_collision.py` y `check_assign_operation.py`.

## Preview: herramienta por operación y stock tallado

- Cada clip usa la herramienta del `ToolController` de **su** operación (radio, largo y longitud de corte); la lista y el estado del Preview muestran su nombre y dimensiones. La transición usa la herramienta de la operación a la que lleva (no se modela el cambio de herramienta).
- El bruto del programa es la caja de la pieza en coordenadas de pieza, 1 mm por lado (`stock_for_program`), y se voxeliza (`Core/voxel_stock.py`, `numpy`): máx. ~800 000 celdas (resolución ≈ 0,5 mm en una pieza de 60×40×30).
- `Core/stock_timeline.py` talla el stock con el eje real (B/C) y el cilindro de corte de cada operación; las transiciones no cortan. Guarda instantáneas al inicio de cada clip, así que el slider puede ir adelante y atrás. Durante la reproducción la malla se reconstruye unas 6 veces por segundo.
- La vista 3D dibuja la forma real de la herramienta (malla de `ToolBit.Shape`, cacheada por herramienta) de cada operación; si no hay malla se usan cilindros. El portaherramientas y el cabezal siguen siendo cilindros.
- El Preview oculta el bruto de los Jobs de orientación mientras está abierto y lo restaura al cerrar. La casilla «Mostrar stock» lo activa o desactiva.
- Límites: la fresa se modela como cilindro (sin esférica/cónica); la malla es en bloques; los G0 también tallan (si atraviesan material se verá); el bruto de CAM no se modifica.
