# IndexedCAM

Workbench para FreeCAD orientado al mecanizado indexado 3+2.

## Objetivos

- Gestionar orientaciones de mecanizado.
- Crear setups automáticamente.
- Calcular los ejes B y C para cabezales B+C.
- Integrarse con CAM Workbench.
- Generar G-code para máquinas indexadas.

## Estado

Cada orientación indexada tiene su propio **Job de CAM** con el modelo y el
bruto ya colocados en su marco (la cara mecanizada en Z=0), así que funcionan
tanto las operaciones 2.5D como las de área del CAM (Adaptive, 3D Surface,
Waterline). Sobre eso: operaciones asociadas a cada orientación, programa,
Preview con stock tallado y colisiones, distancia de seguridad configurable y
postprocesador LinuxCNC (planos `G68.2` + `5axiskins`) con ventana de opciones
por máquina.

Consulta [docs/ROADMAP.md](docs/ROADMAP.md) para las fases de desarrollo,
[docs/TESTING.md](docs/TESTING.md) para instalar y probar el addon en FreeCAD y
[docs/POST_LINUXCNC.md](docs/POST_LINUXCNC.md) para el G-code y la
configuración de la máquina. Hay una máquina simulada lista para probar el 3+2
en [configs/linuxcnc](configs/linuxcnc/README.md).
