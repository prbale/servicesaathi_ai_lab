from .ingest import reingest_active

if __name__ == "__main__":
    for r in reingest_active():
        print(r)
