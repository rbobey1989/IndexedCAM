 # Arquitectura

## Setup

Un **Setup** representa una orientación indexada de la pieza. Contiene:

- **Nombre**: identificador del setup.
- **Normal**: normal de la superficie o plano de trabajo.
- **Sistema XYZ local**: sistema de coordenadas local del setup.
- **A, B y C**: ángulos de los ejes rotativos para alcanzar la orientación.

## Operación

Cada setup agrupa las operaciones CAM que se ejecutan en esa orientación. Las operaciones se interpretan con respecto al sistema XYZ local del setup.

## Postprocesado

El postprocesador genera los movimientos de posicionamiento necesarios antes de las operaciones de cada setup. Estos movimientos llevan la máquina a los ángulos A, B y C asociados al setup.
