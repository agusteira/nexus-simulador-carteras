"""Lógica de negocio de NEXUS Simulador de carteras."""

import collections
import collections.abc

# experta 1.9.4 fija frozendict==1.2, que usa collections.Mapping (eliminado en
# Python 3.10). Restituimos los alias antes de importar experta, así el
# proyecto funciona en Python 3.10+ sin forzar otra versión de frozendict.
for _nombre in ("Mapping", "MutableMapping", "Sequence", "Iterable", "Hashable"):
    if not hasattr(collections, _nombre):
        setattr(collections, _nombre, getattr(collections.abc, _nombre))
