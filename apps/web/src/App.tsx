import { Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import CategoriesPage from "./features/categories/CategoriesPage";
import DashboardPage from "./features/dashboard/DashboardPage";
import ItemsPage from "./features/items/ItemsPage";
import LocationsPage from "./features/locations/LocationsPage";
import SettingsPage from "./features/settings/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="items" element={<ItemsPage />} />
        <Route path="items/:id" element={<ItemsPage />} />
        <Route path="locations" element={<LocationsPage />} />
        <Route path="locations/:id" element={<LocationsPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<DashboardPage />} />
      </Route>
    </Routes>
  );
}
