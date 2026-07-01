interface EnvConfig {
  apiUrl: string;
}

const getEnv = (key: string, defaultValue?: string): string => {
  const value = import.meta.env[key];
  if (!value && defaultValue === undefined) {
    throw new Error(`Environment variable ${key} is required but not defined.`);
  }
  return value || defaultValue || "";
};

export const env: EnvConfig = {
  apiUrl: getEnv("VITE_API_URL", "http://localhost:8000"),
};
