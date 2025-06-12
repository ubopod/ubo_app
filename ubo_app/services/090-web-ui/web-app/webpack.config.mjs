import path, { dirname } from "path";
import { fileURLToPath } from "url";
const __dirname = dirname(fileURLToPath(import.meta.url));

export default {
  entry: "./src/client.tsx",
  output: {
    filename: "main.js",
    path: path.resolve(__dirname, "dist"),
    module: true,
    library: {
      type: "module",
    },
    environment: {
      module: true,
    },
  },
  experiments: {
    outputModule: true,
  },
  resolve: {
    extensions: [".js", ".ts", ".tsx"],
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: "ts-loader",
        exclude: /node_modules/,
      },
      {
        test: /\.css$/i,
        use: ["css-loader"],
      },
    ],
  },
  mode: "development",
};
