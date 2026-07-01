import React from "react";
import { FileText, Upload, Sparkles, CheckCircle } from "lucide-react";

export const ResumesView: React.FC = () => {
  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 m-0">Resume Center</h1>
        <p className="text-sm text-slate-500 mt-1 font-medium">
          Upload, parse, and customize your resumes to fit any job requirements.
        </p>
      </div>

      {/* Drag and drop zone */}
      <div className="bg-white rounded-2xl border-2 border-dashed border-slate-200 hover:border-blue-500/50 p-12 text-center transition-all duration-200 group bg-white shadow-xs">
        <div className="w-16 h-16 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center mx-auto mb-4 group-hover:scale-105 transition-transform duration-200">
          <Upload className="w-6 h-6" />
        </div>
        <h3 className="text-base font-bold text-slate-800">Upload your Resume</h3>
        <p className="text-xs text-slate-400 mt-1 font-medium">Supports PDF, DOCX up to 10MB</p>
        
        <button className="mt-6 px-6 py-2.5 bg-slate-900 hover:bg-slate-800 text-white font-bold text-xs tracking-wide rounded-xl shadow-sm hover:shadow transition-all cursor-pointer">
          Select File
        </button>
      </div>

      {/* Benefits cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-4">
        <div className="bg-white border border-slate-100 rounded-xl p-5 shadow-sm space-y-3">
          <div className="w-10 h-10 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center">
            <Sparkles className="w-5 h-5" />
          </div>
          <h4 className="text-sm font-bold text-slate-800">AI Tailoring</h4>
          <p className="text-xs text-slate-400 leading-relaxed font-medium">
            Automatically optimize your resume experience details for selected job descriptions in our pipeline.
          </p>
        </div>

        <div className="bg-white border border-slate-100 rounded-xl p-5 shadow-sm space-y-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center">
            <CheckCircle className="w-5 h-5" />
          </div>
          <h4 className="text-sm font-bold text-slate-800">Fast Verification</h4>
          <p className="text-xs text-slate-400 leading-relaxed font-medium">
            Verify extracted skills, certifications, and experience points inside a live workspace editor.
          </p>
        </div>

        <div className="bg-white border border-slate-100 rounded-xl p-5 shadow-sm space-y-3">
          <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center">
            <FileText className="w-5 h-5" />
          </div>
          <h4 className="text-sm font-bold text-slate-800">Multiple Formats</h4>
          <p className="text-xs text-slate-400 leading-relaxed font-medium">
            Download your tailored CV in both modern PDF format or editable DOCX formats instantly.
          </p>
        </div>
      </div>
    </div>
  );
};
