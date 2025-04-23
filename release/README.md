### Deployment steps with Cloud Build and Terraform

1. Authenticate using the Cloud SDK and set the GCP project in which you'll
   deploy your resources:

   ```bash 
   gcloud init
   ```

2. Create a Google Cloud Storage Bucket to host your terraform state and source code:
   ```bash
      TFSTATE_BUCKET=$(gcloud config get-value project)-tf-state
      gcloud storage buckets create gs://$TFSTATE_BUCKET --location=<BUCKET_LOCATION>
   ```

3. Enable the Cloud Build API and grant the default Cloud Build service account the following roles


   ```bash
   gcloud services enable cloudbuild.googleapis.com \ && 
   gcloud projects add-iam-policy-binding \
     $(gcloud config get-value project) \
     --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
     --role=roles/storage.admin && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/logging.logWriter && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/iam.serviceAccountCreator && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/iam.serviceAccountTokenCreator && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/serviceusage.serviceUsageAdmin && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/datastore.owner && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/pubsub.admin && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/resourcemanager.projectIamAdmin && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/cloudfunctions.admin && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/cloudscheduler.admin && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/iam.serviceAccountUser && \
   gcloud projects add-iam-policy-binding \
   $(gcloud config get-value project) \
   --member=serviceAccount:$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")"-compute@developer.gserviceaccount.com" \
   --role=roles/artifactregistry.admin

   ```

4. Deploy the necessary resources using terraform:
   ```bash
   gcloud builds submit --config=release/cloudbuild.yaml --substitutions=_TFSTATE_BUCKET=$TFSTATE_BUCKET .
   ```
   Once the deploy finishes, the output URL of the Chat Cloud Run URL should be displayed. Copy this value for the next step.

5. Setup the Chat API Configuration (manual)
* In the GCP console, navigate to the Chat API page and click "Manage"
* Select the "Configuration" tab
* Fill in the necessary fields, the following table represents how you can fill it in:

| Field       |         Value |
| --------    |       ------- |
| App Name    |  User choice  |
| Avatar URL  |  User choice  |
| Description |  User choice  |
| Use interactive features |  Enable |
| Receive 1:1 messages |  Enable  |
| Join spaces and group conversations |  Enable  |
| Connection Setting | HTTP Endpoint URL  |
| HTTP Endpoint URL | Output of Terraform (Chat URL)  |


Click 'Add command', then fill in for `/subscribe`:

| Field       |         Value |
| --------    |       ------- |
| Command ID   |  1  |
| Name  |  Subscribe  |
| Description |  subscribes to release notes channel  |
| Command Type |  Slash command |
| Slash command name |  /subscribe  |
| Dialog |  Enable  |

Click 'Done'.

Click 'Add command', then fill in for `/subscriptions`:

| Field       |         Value |
| --------    |       ------- |
| Command ID   |  2  |
| Name  |  Subscriptions  |
| Description |  List current subscriptions for space  |
| Command Type |  Slash command |
| Slash command name |  /subscriptions  |
| Dialog |  Disabled  |

Click 'Done'.

