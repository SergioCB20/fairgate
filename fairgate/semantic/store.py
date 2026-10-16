"""Repositorio RDF local (Zona 4): guarda el grafo validado de cada ejecución del pipeline y
permite consultar el historial completo, no solo la última ejecución.

Cada ejecución es un grafo con nombre, persistido como `<dataset>-<hash>-<run>.ttl` en el
directorio del repositorio. Los nodos compartidos (lotes, contratos, reglas, atributos) tienen el
mismo IRI en todas las ejecuciones, así que la unión de los grafos los integra sin duplicarlos.
"""
from __future__ import annotations

from pathlib import Path

from rdflib import Dataset, Graph, URIRef

from .queries import run_query


class Repository:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def path_for(self, dataset: str, batch_hash: str, run_id: str) -> Path:
        return self.directory / f"{dataset}-{batch_hash[:8]}-{run_id[:8]}.ttl"

    def add(self, g: Graph, dataset: str, batch_hash: str, run_id: str) -> Path:
        """Persiste el grafo de una ejecución; si ya existía (p. ej., tras nuevos lotes del C4), lo reemplaza."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(dataset, batch_hash, run_id)
        g.serialize(path, format="turtle")
        return path

    def runs(self, dataset: str | None = None) -> list[Path]:
        """Grafos persistidos, del más antiguo al más reciente."""
        pattern = f"{dataset}-*.ttl" if dataset else "*.ttl"
        return sorted(self.directory.glob(pattern), key=lambda p: p.stat().st_mtime)

    def dataset(self, dataset: str | None = None) -> Dataset:
        """Todo el historial como un conjunto de grafos con nombre; su grafo por defecto es la unión."""
        ds = Dataset(default_union=True)
        for path in self.runs(dataset):
            ds.graph(URIRef(f"urn:fairgate:run:{path.stem}")).parse(path, format="turtle")
        return ds

    def query(self, name: str, dataset: str | None = None) -> list[dict]:
        """Pregunta de competencia sobre cada ejecución del historial; cada fila indica su ejecución."""
        rows = []
        for path in self.runs(dataset):
            g = Graph().parse(path, format="turtle")
            rows += [{"ejecucion": path.stem, **row} for row in run_query(g, name)]
        return rows
