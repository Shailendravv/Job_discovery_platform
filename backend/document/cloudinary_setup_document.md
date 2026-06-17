From the API Response After UploadingIf you are uploading files programmatically using Python/FastAPI code, Cloudinary returns the public_id in the JSON response immediately after a successful upload.Here is what your upload code and its response look like:pythonimport cloudinary.uploader

# Uploading a file
response = cloudinary.uploader.upload("my_local_image.jpg", folder="my_uploads")

# Extracting the public_id from the response dictionary
print(response["public_id"]) 
# Output might look like: "my_uploads/a8f9g7h6..."



--------------------------------------------

By Fetching Existing Files via CodeIf you did not save the public IDs into a database during upload, you can list and search for your files using Cloudinary’s Admin API or Search API.pythonimport cloudinary.api

# List your most recent uploaded assets
resources = cloudinary.api.resources(max_results=10)

for asset in resources["resources"]:
    print(asset["public_id"])  # This prints the public ID of each file

----------------------------------------

How to use it in your FastAPI endpointOnce you have retrieved the public ID from your database or dashboard, you pass it as a path parameter to your FastAPI route.For example, if your public ID is my_uploads/profile_pic, your API request URL will look like this:texthttp://127.0.0


-----------------------------------

The "Blocked for delivery" status occurs because Cloudinary automatically restricts PDF and ZIP file delivery on all Free accounts to prevent malware distribution. Even if the file uploads successfully, its URL will return an error until you unblock this setting.To download this specific file without any difficulty, you must change your Cloudinary account settings and adjust how FastAPI handles the file extension.Step 1: Unblock PDF Delivery in Cloudinary DashboardThis is an account-level setting that overrides your code. You only need to do this once:Log into your Cloudinary Management Console.Click on the Settings (gear icon), usually located in the bottom-left corner.Navigate to the Security tab.Scroll down until you find the option labeled "Restrict PDF and ZIP files delivery" (or "Allow delivery of PDF and ZIP files").Uncheck the restriction (or check "Allow delivery") and click Save.Step 2: Extracting your Public IDBased on your info panel, your exact identifier is:public_id: "tailored/9fndjnjdndjndjndjndnj/cover_letter"Important: In Cloudinary, the file extension .pdf is not part of the public_id string. When passing it to your code, omit .pdf.Step 3: FastAPI Code Configuration for PDFsCloudinary treats PDFs as an "image" resource type internally because they allow page-by-page visual transformations. You must specify resource_type="image" and explicitly append the .pdf extension to the delivery URL generation.Here is how your FastAPI endpoint should be written to successfully download this file:pythonimport os
import httpx
import cloudinary
import cloudinary.utils
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

app = FastAPI()

# Cloudinary Config (Ensure secure=True is set)
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

@app.get("/download-pdf")
async def download_pdf():
    # Hardcoded based on your exact dashboard information
    public_id = "tailored/9fndjnjdndjndjndjndnj/cover_letter" 
    
    try:
        # 1. Generate the URL. Note the forced format='pdf' and resource_type='image'
        cloudinary_url, _ = cloudinary.utils.cloudinary_url(
            public_id, 
            resource_type="image",
            format="pdf"
        )
        
        # 2. Stream the file data from Cloudinary
        async def file_streamer():
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", cloudinary_url) as response:
                    if response.status_code != 200:
                        raise HTTPException(
                            status_code=response.status_code, 
                            detail="Cloudinary blocked delivery. Check Step 1 settings."
                        )
                    async for chunk in response.iter_bytes():
                        yield chunk

        # 3. Clean filename for the client browser
        filename = "cover_letter.pdf"

        # 4. Stream response back to user
        return StreamingResponse(
            file_streamer(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
Use code with caution.Would you like to modify this code so it accepts the Public ID dynamically as a query or path parameter instead of hardcoding it?