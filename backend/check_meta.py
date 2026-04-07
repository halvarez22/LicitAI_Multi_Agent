import chromadb

def check():
    client = chromadb.HttpClient(host='vector-db', port=8000)
    coll = client.get_collection('issste-bcs-2024-official')
    res = coll.get(limit=1)
    meta = res['metadatas'][0]
    print(f"Metadata: {meta}")
    print(f"Page value: {meta.get('page')}")
    print(f"Page type: {type(meta.get('page'))}")

if __name__ == "__main__":
    check()
