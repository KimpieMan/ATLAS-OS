import os
from waitress import serve
from atlas.app import create_app

if __name__ == '__main__':
    port = int(os.environ.get('ATLAS_PORT', '8080'))
    serve(create_app(port=port), host='127.0.0.1', port=port, threads=4)
