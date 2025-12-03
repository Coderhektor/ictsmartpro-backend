import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  // BU SATIRI EKLE → kök path’e gelen her şeye 200 döndürsün
  app.getHttpAdapter().get('/', (req, res) => {
    res.status(200).json({ status: 'ok', message: 'ictsmartpro-backend canlı!' });
  });

  // Eğer CORS açıksa zaten vardır, yoksa ekle
  app.enableCors();

  await app.listen(process.env.PORT || 8080);
}
bootstrap();