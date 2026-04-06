export function createAnsibleApi(session) {
  const basePath = "/api/ansible/playbooks";

  async function request(method, path, body) {
    const fullPath = `${basePath}${path}`;
    const result = await window.__TAURI__.core.invoke("api_proxy", {
      serverUrl: session.serverUrl,
      token: session.token,
      method,
      path: fullPath,
      body: body ? JSON.stringify(body) : null,
    });
    return result;
  }

  return {
    fetchPlaybooks() {
      return request("GET", "");
    },
    fetchContent(id) {
      return request("GET", `/${id}/content`);
    },
    fetchServers() {
      return window.__TAURI__.core.invoke("api_proxy", {
        serverUrl: session.serverUrl,
        token: session.token,
        method: "GET",
        path: "/api/servers",
        body: null,
      });
    },
  };
}
