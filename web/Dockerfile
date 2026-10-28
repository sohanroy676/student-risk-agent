FROM node:24-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Both values are fixed into the build: the rewrite target in next.config.ts and the dev sign-in
# switch (off unless a developer turns it on; see .env.example).
ARG API_URL=http://api:8000
ARG NEXT_PUBLIC_DEV_TOKEN_LOGIN=false
ENV API_URL=$API_URL NEXT_PUBLIC_DEV_TOKEN_LOGIN=$NEXT_PUBLIC_DEV_TOKEN_LOGIN
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
