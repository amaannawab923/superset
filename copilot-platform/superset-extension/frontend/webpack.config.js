/**
 * Module Federation config for the Copilot chat extension.
 * Superset loads the `./index` module from this remote and injects a
 * per-extension `@apache-superset/core` instance into the share scope.
 */
const path = require('path');
const { ModuleFederationPlugin } = require('webpack').container;
const packageConfig = require('./package');
const extensionConfig = require('../extension.json');

module.exports = (env, argv) => {
  const isProd = argv.mode === 'production';

  return {
    entry: isProd ? {} : './src/index.tsx',
    mode: isProd ? 'production' : 'development',
    devServer: {
      port: 3000,
      headers: { 'Access-Control-Allow-Origin': '*' },
    },
    output: {
      clean: true,
      filename: isProd ? undefined : '[name].[contenthash].js',
      chunkFilename: '[name].[contenthash].js',
      path: path.resolve(__dirname, 'dist'),
      publicPath: `/api/v1/extensions/${extensionConfig.publisher}/${extensionConfig.name}/`,
    },
    resolve: { extensions: ['.ts', '.tsx', '.js', '.jsx'] },
    module: {
      rules: [{ test: /\.tsx?$/, use: 'ts-loader', exclude: /node_modules/ }],
    },
    plugins: [
      new ModuleFederationPlugin({
        name: 'local_copilot',
        filename: 'remoteEntry.[contenthash].js',
        exposes: { './index': './src/index.tsx' },
        shared: {
          react: {
            singleton: true,
            requiredVersion: packageConfig.peerDependencies.react,
            import: false,
          },
          'react-dom': {
            singleton: true,
            requiredVersion: packageConfig.peerDependencies['react-dom'],
            import: false,
          },
          antd: {
            singleton: true,
            requiredVersion: packageConfig.peerDependencies.antd,
            import: false,
          },
          '@apache-superset/core': { singleton: true, import: false },
        },
      }),
    ],
  };
};
