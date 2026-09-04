"""Load both merchant catalogs into Neo4j.

Prereqs:
    docker compose up -d          # start Neo4j
    # ensure .env NEO4J_* match docker-compose.yml (neo4j/password123)

Run:
    python -m scripts.load_graph
"""
import logging

from app.matching.graph import GraphUnavailable, get_graph

logging.basicConfig(level=logging.INFO, format="  [%(name)s] %(message)s")


def main() -> None:
    graph = get_graph()
    try:
        summary = graph.load_catalog()
    except GraphUnavailable as exc:
        print(f"\nCould not load graph: {exc}")
        print("Start Neo4j with `docker compose up -d` and check .env creds.\n")
        return
    finally:
        graph.close()

    print(f"\nLoaded {summary['nodes']} products and {summary['edges']} "
          f"COMPLEMENTS edges into Neo4j.")
    print("Browse at http://localhost:7474  (try: MATCH (n) RETURN n)\n")


if __name__ == "__main__":
    main()
