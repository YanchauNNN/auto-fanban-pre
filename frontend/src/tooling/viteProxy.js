var _a;
export var apiProxyTarget = (_a = process.env.VITE_API_PROXY_TARGET) !== null && _a !== void 0 ? _a : "http://127.0.0.1:8010";
export var apiProxyConfig = {
    "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
    },
};
