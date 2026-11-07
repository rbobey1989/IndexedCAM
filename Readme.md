# IndexedCAM

Workbench para FreeCAD orientado al mecanizado indexado 3+2.

## Objetivos

- Gestionar orientaciones de mecanizado.
- Crear setups automáticamente.
- Calcular los ejes B y C para cabezales B+C.
- Integrarse con CAM Workbench.
- Generar G-code para máquinas indexadas.

## Estado

El flujo completo funciona sobre el Job nativo de CAM: orientaciones indexadas
dentro del Job, operaciones asociadas a cada orientación, programa, Preview con
stock y colisiones, distancia de seguridad configurable, y postprocesador
LinuxCNC (planos `G68.2` + `5axiskins`) con ventana de opciones por máquina.

Consulta [docs/ROADMAP.md](docs/ROADMAP.md) para las fases de desarrollo,
[docs/TESTING.md](docs/TESTING.md) para instalar y probar el addon en FreeCAD y
[docs/POST_LINUXCNC.md](docs/POST_LINUXCNC.md) para el G-code y la
configuración de la máquina. Hay una máquina simulada lista para probar el 3+2
en [configs/linuxcnc](configs/linuxcnc/README.md).
