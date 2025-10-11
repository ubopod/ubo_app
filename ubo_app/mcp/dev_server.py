import uvicorn

if __name__ == '__main__':
    uvicorn.run(
        'ubo_app.mcp.server:get_app',
        host='localhost',
        port=8765,
        reload=True,
    )
