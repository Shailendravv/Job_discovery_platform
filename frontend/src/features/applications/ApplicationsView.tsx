import React from "react";
import { CheckSquare, Calendar, ChevronRight, ArrowUpRight } from "lucide-react";

export const ApplicationsView: React.FC = () => {
  const mockApplications = [
    {
      title: "Frontend Developer (React)",
      company: "InnovateTech",
      status: "Interview Scheduled",
      statusColor: "bg-emerald-50 text-emerald-700 border-emerald-200",
      date: "Jun 15, 2026",
    },
    {
      title: "Senior UI/UX Designer",
      company: "DesignScale AI",
      status: "Applied",
      statusColor: "bg-blue-50 text-blue-700 border-blue-200",
      date: "Jun 12, 2026",
    },
    {
      title: "DevOps Engineer",
      company: "CloudStack Solutions",
      status: "Saved",
      statusColor: "bg-slate-50 text-slate-600 border-slate-200",
      date: "Jun 10, 2026",
    },
  ];

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 m-0">Applications Tracker</h1>
        <p className="text-sm text-slate-500 mt-1 font-medium">
          Track interview timelines, applications, and saved pipeline listings.
        </p>
      </div>

      {/* Applications list */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h3 className="text-sm font-bold text-slate-800 flex items-center">
            <CheckSquare className="w-4.5 h-4.5 text-blue-600 mr-2" />
            Active Processes
          </h3>
          <span className="text-[10px] font-bold text-slate-400 bg-slate-100 px-2.5 py-0.5 rounded-full uppercase">
            3 Listings
          </span>
        </div>

        <div className="divide-y divide-slate-100">
          {mockApplications.map((app, index) => (
            <div
              key={index}
              className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-slate-50/40 transition-colors"
            >
              <div className="space-y-1">
                <h4 className="text-sm font-bold text-slate-900 flex items-center hover:underline cursor-pointer">
                  {app.title}
                  <ArrowUpRight className="w-3.5 h-3.5 text-slate-400 ml-1 shrink-0" />
                </h4>
                <p className="text-xs font-semibold text-slate-400">{app.company}</p>
              </div>

              <div className="flex items-center space-x-4 justify-between sm:justify-start">
                <span className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full border ${app.statusColor} uppercase`}>
                  {app.status}
                </span>
                <div className="flex items-center text-slate-400 text-xs font-semibold">
                  <Calendar className="w-3.5 h-3.5 mr-1" />
                  {app.date}
                  <ChevronRight className="w-4 h-4 ml-2" />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
