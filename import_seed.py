from app import init_db, import_seed_csv

if __name__ == "__main__":
    init_db()
    result = import_seed_csv(force=True)
    print(result)
