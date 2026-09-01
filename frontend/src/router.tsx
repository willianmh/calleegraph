import { createBrowserRouter } from 'react-router-dom';

import { App } from '@/App';
import { GraphScreen } from '@/features/graph/GraphScreen';
import { RepositoriesScreen } from '@/features/repositories/RepositoriesScreen';
import { SettingsScreen } from '@/features/settings/SettingsScreen';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <GraphScreen /> },
      { path: 'repositories', element: <RepositoriesScreen /> },
      { path: 'settings', element: <SettingsScreen /> },
    ],
  },
]);
