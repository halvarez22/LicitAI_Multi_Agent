import chromadb

def test():
    client = chromadb.HttpClient(host='vector-db', port=8000)
    collection_name = 'issste-bcs-2024-official'
    try:
        coll = client.get_collection(collection_name)
        query = "cronograma fechas junta aclaraciones apertura proposiciones fallo garantías seriedad requisitos filtro"
        res = coll.query(query_texts=[query], n_results=12)
        print(f"Colección: {collection_name}")
        print(f"Documentos encontrados: {len(res['documents'][0]) if res['documents'] else 0}")
        if res['documents'] and res['documents'][0]:
            for i, doc in enumerate(res['documents'][0]):
                print(f"\n[{i+1}] {res['metadatas'][0][i].get('page')} -> {doc[:150]}...")
        else:
            print("No se encontraron documentos para esta query.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test()
