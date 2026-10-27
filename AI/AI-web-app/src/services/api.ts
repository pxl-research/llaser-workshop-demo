const LOCAL_DEV_API_URL = "/";

const normalizeBaseUrl = (baseUrl: string) =>
  baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;

export const getApiBaseUrl = () => {
  const configuredBaseUrl = import.meta.env.VITE_API_URL;

  if (configuredBaseUrl) {
    return normalizeBaseUrl(configuredBaseUrl);
  }

  if (import.meta.env.DEV) {
    return LOCAL_DEV_API_URL;
  }

  return normalizeBaseUrl(import.meta.env.BASE_URL);
};

export const apiUrl = (path: string) =>
  `${getApiBaseUrl()}${path.replace(/^\/+/, "")}`;
