# Build stage
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci
COPY . .
RUN npx ng build --configuration=production

# Runtime stage
FROM nginx:alpine AS runtime
COPY --from=build /app/dist/lead-pulse-web/browser /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
