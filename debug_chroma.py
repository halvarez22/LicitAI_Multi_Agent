import chromadb
import os

def test():
    try:
        chroma_host = 'vector-db'
        chroma_port = '8000'
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        print('Heartbeat:', client.heartbeat())
        print('Tenant:', client._tenant)
        print('Database:', client._database)
        print('Collections:', client.list_collections())
    except Exception as e:
        print('Error:', e)

if __name__ == '__main__':
    test()
