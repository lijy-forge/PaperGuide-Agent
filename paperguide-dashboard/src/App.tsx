import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { LoadingState } from "./components/LoadingState";

const DashboardPage = lazy(() =>
  import("./pages/DashboardPage").then((module) => ({
    default: module.DashboardPage
  }))
);
const NewResearchPage = lazy(() =>
  import("./pages/NewResearchPage").then((module) => ({
    default: module.NewResearchPage
  }))
);
const TaskDetailPage = lazy(() =>
  import("./pages/TaskDetailPage").then((module) => ({
    default: module.TaskDetailPage
  }))
);

export default function App() {
  return (
    <Suspense fallback={<LoadingState label="正在加载页面" />}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/research/new" element={<NewResearchPage />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
